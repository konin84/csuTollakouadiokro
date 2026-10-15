@echo off
rem Double-cliquer pour installer FSU Caisse (demande les droits administrateur).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File \"%~dp0installer.ps1\"'"
