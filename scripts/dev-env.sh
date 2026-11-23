# Source this file; do not execute it.   . scripts/dev-env.sh
#
# Points every development tool at the external development volume, so large
# SDKs, caches and build output stay off the Mac's internal disk. Nothing here
# changes a system-wide setting: it only exports variables for the current shell.
#
# The volume is an APFS disk image stored on the T7 SSD. Mount it first:
#     open /Volumes/T7/EdupreneursDev.sparsebundle        (or: make dev-volume)

export EDU_DEV_VOLUME="${EDU_DEV_VOLUME:-/Volumes/EdupreneursDev}"

if [ ! -d "$EDU_DEV_VOLUME/android-sdk" ]; then
  echo "dev-env: $EDU_DEV_VOLUME is not mounted. Plug in the T7 SSD and run:" >&2
  echo "         open /Volumes/T7/EdupreneursDev.sparsebundle" >&2
  return 1 2>/dev/null || exit 1
fi

_edu_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Android: SDK + NDK, emulator devices, Gradle downloads and caches
export ANDROID_HOME="$EDU_DEV_VOLUME/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_AVD_HOME="$EDU_DEV_VOLUME/android-avd"
export GRADLE_USER_HOME="$EDU_DEV_VOLUME/gradle"
# JDK 17 is what React Native 0.88 builds with; it lives in the repository's .tools/
[ -d "$_edu_repo/.tools/jdk17/Contents/Home" ] && export JAVA_HOME="$_edu_repo/.tools/jdk17/Contents/Home"

# iOS: Xcode itself stays on the internal disk; only build output goes to the volume
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode-26.6.app/Contents/Developer}"
export EDU_IOS_DERIVED_DATA="$EDU_DEV_VOLUME/xcode-derived-data/edupreneurs"

# Package caches (Python and Node downloads)
export UV_CACHE_DIR="$EDU_DEV_VOLUME/caches/uv"
export npm_config_cache="$EDU_DEV_VOLUME/caches/npm"
export CP_HOME_DIR="$EDU_DEV_VOLUME/caches/cocoapods"

export LANG="${LANG:-en_US.UTF-8}"
case ":$PATH:" in *":$ANDROID_HOME/platform-tools:"*) ;; *) export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH" ;; esac
unset _edu_repo
