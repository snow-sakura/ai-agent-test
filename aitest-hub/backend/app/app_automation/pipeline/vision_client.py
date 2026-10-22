# -*- coding: utf-8 -*-
"""视觉模型补充语义(按需调用 OpenAI 兼容多模态接口;无配置时走规则降级)。"""
import base64
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AIConfig

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = (
    "你是 APP UI 分析助手。请根据页面截图和控件列表,回答:每个控件的视觉角色/业务功能是什么?"
    "哪个区域是真正可点击区域?输出 JSON 数组,每项 {control_id, visual_role, click_region_hint, evidence}。"
    "只输出 JSON,不要解释。"
)


async def _pick_ai_config(db: AsyncSession) -> Optional[AIConfig]:
    result = await db.execute(select(AIConfig).order_by(AIConfig.is_default.desc(), AIConfig.id.asc()))
    return result.scalars().first()


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _fallback_semantics(profiles: List[Dict[str, Any]], gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """无 AI 配置时的规则降级:基于 class/bounds 位置推断视觉角色"""
    results = []
    for g in gaps:
        target = next((p for p in profiles if p["control_id"] == g["control_id"]), None)
        if not target:
            continue
        xml = target["xml"]
        cls = (xml.get("class") or "")
        center = xml.get("center") or [0, 0]
        x, y = center
        if "EditText" in cls:
            role = "文本输入框(推断)"
        elif "ImageView" in cls:
            if x > 800:
                role = "右上角图标按钮(推断:可能是扫一扫/更多)"
            elif x < 150:
                role = "左上角返回按钮(推断)"
            else:
                role = "中部图标按钮(推断:功能入口)"
        else:
            role = f"可交互控件(推断:{cls.rsplit('.', 1)[-1]})"
        results.append({
            "control_id": g["control_id"],
            "visual_role": role,
            "click_region_hint": xml.get("bounds"),
            "evidence": "规则降级推断(未调用视觉模型,无 AI 配置)",
            "simulated": True,
        })
    return results


async def supplement_semantics(db: AsyncSession, screenshot_path: str,
                               profiles: List[Dict[str, Any]],
                               gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只让视觉模型补充缺失信息;输出视觉候选语义,不是正式定位器。"""
    config = await _pick_ai_config(db)
    if not config or not config.api_key:
        return _fallback_semantics(profiles, gaps)

    base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    controls_summary = [
        {"control_id": p["control_id"], "class": p["xml"].get("class"), "text": p["xml"].get("text"),
         "bounds": p["xml"].get("bounds")}
        for p in profiles
    ]
    gap_ids = [g["control_id"] for g in gaps]
    user_text = (
        f"控件列表: {json.dumps(controls_summary, ensure_ascii=False)}\n"
        f"重点关注存在视觉缺口的控件: {gap_ids}"
    )
    try:
        image_b64 = _encode_image(screenshot_path)
    except Exception as e:
        logger.warning(f"截图读取失败,使用规则降级: {e}")
        return _fallback_semantics(profiles, gaps)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                json={
                    "model": config.model_name or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": VISION_SYSTEM_PROMPT},
                        {"role": "user", "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                        ]},
                    ],
                    "temperature": 0.2,
                },
                headers={"Authorization": f"Bearer {config.api_key}"},
            )
        if resp.status_code != 200:
            logger.warning(f"视觉模型 HTTP {resp.status_code},规则降级")
            return _fallback_semantics(profiles, gaps)
        content = resp.json()["choices"][0]["message"]["content"]
        # 提取 JSON 数组
        start, end = content.find("["), content.rfind("]")
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end + 1])
            for item in parsed:
                item.setdefault("simulated", False)
            return parsed
    except Exception as e:
        logger.warning(f"视觉模型调用失败,规则降级: {e}")
    return _fallback_semantics(profiles, gaps)
