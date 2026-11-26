# Android release bundle and experimental flags

The PR #25 device report records an incremental Gradle release build retaining the previous flags-on JavaScript bundle after the build environment changed. The symptom was first-run onboarding in a build intended to have all student feature flags off.

In the correction checkout, two Android production Metro exports used fresh output directories and cleared transform caches. Only the first export set `EXPO_PUBLIC_FF_ONBOARDING=1`. Inspection of the generated JavaScript found the literal `"1"` in the onboarding initializer in the first export. The clean flags-off export passed `undefined` to all six flag initializers. These checks used `expo export --platform android --clear --no-bytecode` so the initializers could be inspected directly.

For a release following an experimental build, clean the Android build outputs and disable Gradle build-cache reuse for the production assembly. A separate build-system change can declare the public feature flags as inputs to the React Native bundle task and test incremental on-to-off switching. The correction PR leaves that incremental-build finding open.
