"""PyInstaller entry point for InvestIQ-Background.exe (no window; used by the scheduled task)."""
from investiq.desktop import background_main

raise SystemExit(background_main())
