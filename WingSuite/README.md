# WingSuite

A first-person wingsuit and grappling-hook exploration game. Open `WingSuite.html` in a browser; there's nothing to install.

Each world is generated from a seed: mountain ranges, deep valleys, river gorges, lakes, forests and clouds. There's no goal. You jump off peaks, carve through canyons and grapple your way up cliffs.

## Controls

| Input | Action |
| --- | --- |
| Mouse | Look, and steer the wingsuit |
| W A S D | Walk. In the suit: W tucks (faster), S flares (brakes), A/D turn |
| Shift | Sprint |
| Space | Jump. In the air: open or close the wingsuit |
| Left mouse / Q (hold) | Grapple and swing |
| Right mouse / E (hold) | Grapple and reel in |
| R | Teleport to a nearby mountain top |
| T | Teleport next to a friend (cycles through them) |
| V | Switch between first and third person |
| Esc | Pause, settings, room code |

## Multiplayer

1. One player clicks **Host multiplayer** and gets a 5-letter room code (shown top right and in the pause menu).
2. The friend opens their own copy of `WingSuite.html` and enters the code under **Join a friend**.

Players connect directly over WebRTC (PeerJS). The free public PeerJS server only introduces the two browsers to each other. Each browser builds the world itself from the host's seed, so only positions are sent. The host's tab relays everyone's position, so keep it open. Both players need an internet connection.

Three.js and PeerJS are loaded from public CDNs.
