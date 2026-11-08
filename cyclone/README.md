# Cyclone

An arctic-minimal Minecraft launcher with offline mode and a built-in FPS mod pack.

## Run
```
pip install -r requirements.txt
python launcher.py
```
Opens at http://127.0.0.1:8765. Python 3.9+. Java is downloaded automatically for the chosen version.

## What's inside
- **Offline mode**: pick a username, no account needed (same UUID vanilla derives for offline players).
- **Fabric** installed automatically for any release version.
- **Inbuilt mods**: Sodium, Lithium, FerriteCore, Entity Culling, ImmediatelyFast, ModernFix, Krypton, Dynamic FPS, Sodium Extra, Mod Menu. Downloaded from Modrinth on first launch; toggle each in the UI.
- **mods/ folder**: drop extra Fabric jars there.
- Tuned JVM flags and adjustable RAM.
- Splash screen: "Stay cool. Fly with Cyclone."

## Notes
- Offline mode joins singleplayer, LAN and offline-mode servers only. Online servers need a Microsoft login, which isn't included.
- Game files live in `cyclone_data/`.
