# -*- coding: utf-8 -*-
"""设备管理:真实 ADB 发现/连接 + 模拟设备模式"""
import subprocess
import re
from typing import Any, Dict, List, Optional

from app.app_automation.engine import mock_device


class AdbManager:
    def __init__(self, adb_path: str = "adb", mock_mode: bool = True):
        self.adb_path = adb_path
        self.mock_mode = mock_mode

    def _verify_adb(self) -> bool:
        try:
            r = subprocess.run([self.adb_path, "version"], capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False

    def list_devices(self) -> Dict[str, Any]:
        """发现设备:真实 ADB devices + mock 模拟设备"""
        devices: List[Dict[str, Any]] = []
        if not self.mock_mode and self._verify_adb():
            try:
                r = subprocess.run([self.adb_path, "devices", "-l"], capture_output=True, text=True, timeout=15)
                for line in r.stdout.strip().splitlines()[1:]:
                    if not line.strip():
                        continue
                    parts = line.split()
                    dev_id, state = parts[0], parts[1]
                    model = next((p.split(":")[1] for p in parts[2:] if p.startswith("model:")), "")
                    devices.append({
                        "device_id": dev_id, "name": model or dev_id, "state": state,
                        "is_mock": False, "connection_type": "real_device" if not dev_id.startswith("emulator") else "emulator",
                    })
            except Exception as e:
                return {"success": False, "message": f"ADB 执行失败: {e}", "devices": []}
        if not devices:
            devices = [
                {"device_id": "mock-emulator-5554", "name": "Pixel 4 (模拟)", "state": "device", "is_mock": True, "connection_type": "emulator", "android_version": "13"},
                {"device_id": "mock-emulator-5556", "name": "Pixel 6 Pro (模拟)", "state": "device", "is_mock": True, "connection_type": "emulator", "android_version": "14"},
            ]
        return {"success": True, "message": f"发现 {len(devices)} 个设备", "devices": devices}

    def connect_device(self, ip_address: str, port: int = 5555) -> Dict[str, Any]:
        if self.mock_mode or ip_address.startswith("mock"):
            return {"success": True, "message": f"已连接(模拟) {ip_address}:{port}", "device_id": f"mock-{ip_address}:{port}"}
        if not self._verify_adb():
            return {"success": False, "message": "ADB 不可用,请检查配置"}
        try:
            r = subprocess.run([self.adb_path, "connect", f"{ip_address}:{port}"], capture_output=True, text=True, timeout=15)
            ok = "connected" in (r.stdout or "").lower()
            return {"success": ok, "message": (r.stdout or r.stderr).strip(), "device_id": f"{ip_address}:{port}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def disconnect_device(self, device_id: str) -> Dict[str, Any]:
        if self.mock_mode or device_id.startswith("mock"):
            return {"success": True, "message": f"已断开(模拟) {device_id}"}
        try:
            r = subprocess.run([self.adb_path, "disconnect", device_id], capture_output=True, text=True, timeout=10)
            return {"success": True, "message": (r.stdout or "已断开").strip()}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def is_device_connected(self, device_id: str) -> bool:
        if self.mock_mode or device_id.startswith("mock"):
            return True
        if not self._verify_adb():
            return False
        try:
            r = subprocess.run([self.adb_path, "devices"], capture_output=True, text=True, timeout=10)
            return any(line.startswith(device_id) and "device" in line for line in r.stdout.splitlines())
        except Exception:
            return False

    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        if self.mock_mode or device_id.startswith("mock"):
            session = mock_device.get_mock_session(device_id)
            return {
                "device_id": device_id, "is_mock": True,
                "android_version": "13", "screen": "1080x2400", "model": "Mock Device",
                "current_page": session.page, "fingerprint": session.fingerprint(),
            }
        info: Dict[str, Any] = {"device_id": device_id, "is_mock": False}
        props = ["ro.build.version.release", "ro.product.model", "ro.product.brand"]
        for p in props:
            try:
                r = subprocess.run([self.adb_path, "-s", device_id, "shell", "getprop", p], capture_output=True, text=True, timeout=10)
                info[p.split(".")[-1]] = r.stdout.strip()
            except Exception:
                info[p.split(".")[-1]] = ""
        return info

    def screenshot(self, device_id: str, save_path: str) -> Dict[str, Any]:
        """设备截图(真机 screencap / mock PIL 渲染)"""
        if self.mock_mode or device_id.startswith("mock"):
            try:
                path = mock_device.get_mock_session(device_id).screenshot(save_path)
                return {"success": True, "path": path, "is_mock": True}
            except Exception as e:
                return {"success": False, "message": str(e)}
        try:
            os_tmp = "/tmp/_adb_screen.png"
            r = subprocess.run([self.adb_path, "-s", device_id, "shell", "screencap", "-p", os_tmp], capture_output=True, timeout=20)
            if r.returncode != 0:
                return {"success": False, "message": "screencap 失败"}
            r2 = subprocess.run([self.adb_path, "-s", device_id, "pull", os_tmp, save_path], capture_output=True, timeout=20)
            if r2.returncode != 0:
                return {"success": False, "message": "pull 失败"}
            return {"success": True, "path": save_path}
        except Exception as e:
            return {"success": False, "message": str(e)}
