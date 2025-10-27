# app_autostart.py
# Version: 1.0.0
# Windows autostart management via Task Scheduler and Registry fallback.
# Separated from app_config.py to maintain configuration purity.

import subprocess
import tempfile
import winreg
from pathlib import Path
from typing import Tuple
import logging

logger = logging.getLogger(__name__)

class AutostartManager:
    """Manages Windows autostart via Task Scheduler and Registry fallback."""

    def __init__(self, exe_path: Path):
        self.exe_path = exe_path

    def ensure_autostart(self, method: str = "scheduler") -> bool:
        """Set up autostart using the specified method."""
        if method == "scheduler":
            return self._setup_task_scheduler()
        elif method == "registry":
            return self._setup_registry_autostart()
        else:
            logger.error(f"Unknown autostart method: {method}")
            return False

    def _setup_task_scheduler(self) -> bool:
        """Set up autostart via Windows Task Scheduler."""
        try:
            task_name = "DriveRevenant"
            exe_path = str(self.exe_path)

            # Create XML for the task
            xml_content = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Drive Revenant - Keep drives awake</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe_path}</Command>
    </Exec>
  </Actions>
</Task>'''

            # Write XML to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False, encoding='utf-16') as f:
                f.write(xml_content)
                xml_path = f.name

            try:
                # Create the task
                result = subprocess.run([
                    'schtasks', '/create', '/tn', task_name, '/xml', xml_path, '/f'
                ], capture_output=True, text=True, check=True)

                logger.info("Task Scheduler autostart configured successfully")
                return True

            finally:
                # Clean up temp file
                try:
                    import os
                    os.unlink(xml_path)
                except:
                    pass

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create Task Scheduler entry: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error setting up Task Scheduler: {e}")
            return False

    def _setup_registry_autostart(self) -> bool:
        """Set up autostart via Windows Registry Run key."""
        try:
            exe_path = str(self.exe_path)
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "DriveRevenant", 0, winreg.REG_SZ, exe_path)

            logger.info("Registry autostart configured successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to set up Registry autostart: {e}")
            return False

    def verify_autostart(self) -> Tuple[bool, str, str]:
        """Verify autostart configuration and return (is_valid, method, error_message)."""
        # Check Task Scheduler first
        try:
            result = subprocess.run([
                'schtasks', '/query', '/tn', 'DriveRevenant', '/fo', 'csv'
            ], capture_output=True, text=True)

            if result.returncode == 0:
                # Task exists, verify it points to the right executable
                if str(self.exe_path) in result.stdout:
                    return True, "scheduler", ""
                else:
                    return False, "scheduler", "Task exists but points to wrong executable"
            else:
                # Task doesn't exist, check Registry
                return self._verify_registry_autostart()

        except Exception as e:
            logger.error(f"Error checking Task Scheduler: {e}")
            return self._verify_registry_autostart()

    def _verify_registry_autostart(self) -> Tuple[bool, str, str]:
        """Verify Registry autostart configuration."""
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, "DriveRevenant")
                    if value == str(self.exe_path):
                        return True, "registry", ""
                    else:
                        return False, "registry", "Registry entry exists but points to wrong executable"
                except FileNotFoundError:
                    return False, "registry", "No Registry autostart entry found"

        except Exception as e:
            return False, "registry", f"Error checking Registry: {e}"

    def remove_autostart(self, method: str = None) -> bool:
        """Remove autostart configuration."""
        success = True

        if method is None or method == "scheduler":
            success &= self._remove_task_scheduler()

        if method is None or method == "registry":
            success &= self._remove_registry_autostart()

        return success

    def _remove_task_scheduler(self) -> bool:
        """Remove Task Scheduler autostart."""
        try:
            result = subprocess.run([
                'schtasks', '/delete', '/tn', 'DriveRevenant', '/f'
            ], capture_output=True, text=True)

            if result.returncode == 0:
                logger.info("Task Scheduler autostart removed")
                return True
            else:
                logger.warning("Task Scheduler entry may not have existed")
                return True  # Not an error if it didn't exist

        except Exception as e:
            logger.error(f"Error removing Task Scheduler entry: {e}")
            return False

    def _remove_registry_autostart(self) -> bool:
        """Remove Registry autostart."""
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, "DriveRevenant")
                    logger.info("Registry autostart removed")
                    return True
                except FileNotFoundError:
                    logger.warning("Registry autostart entry may not have existed")
                    return True  # Not an error if it didn't exist

        except Exception as e:
            logger.error(f"Error removing Registry autostart: {e}")
            return False
