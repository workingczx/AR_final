# Verification notes

- **NasalSeg audit.** The downloaded v2 archive matched the published MD5. All 130 CT–label pairs were parsed. Of these, 118 agreed in shape, origin, axes and spacing within numeric tolerance. P002 passed the physical grid check. The full audit is in [nasalseg-audit.json](../python-demo/nasalseg-audit.json).
- **P002 Python.** The verified route begins in CT air outside the target label, enters the label, stops before an invalid move and returns to the start. The report includes the quantitative pose trace. No manually annotated external nostril landmark was available, so the label crossing is the measured result.
- **p04_left Python.** The original scene passed 14 automated checks and five straight or angled approach routes. Rejected motions kept all derived transforms fixed. Playback checked the appearance and disappearance of the synthetic red region on entry and withdrawal.
- **Unity Mac.** The Unity regression test reproduced 16.8 mm insertion and withdrawal. Rendered frames were inspected before and after insertion and model switching.
- **Quest APK.** A signed ARM64 APK was generated. The manifest contains Quest 3 support, OpenXR and passthrough declarations. A headset was unavailable for physical validation when the build was made.
