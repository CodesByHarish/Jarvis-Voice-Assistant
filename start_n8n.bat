@echo off
title n8n Workflow Server
set N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false
echo Starting local n8n server on http://localhost:5678 ...
npx -y n8n start
