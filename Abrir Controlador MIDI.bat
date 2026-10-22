@echo off
cd /d "%~dp0"
title Controlador MIDI
where python >nul 2>nul && (python controlador.py) || (py controlador.py)
