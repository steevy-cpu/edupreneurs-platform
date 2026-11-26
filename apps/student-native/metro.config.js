// Metro configuration.
//
// The only customisation: keep the Design-00 fixture previews out of production
// bundles. Expo Router turns every file under src/app into a route, so the
// preview routes (src/app/design) and their fixture data (src/design/preview)
// would otherwise ship inside the release app. They are development tools.
//
//   development server (expo start)            previews included
//   production bundle (release build, export)  previews excluded
//   production bundle with EXPO_PUBLIC_DESIGN_PREVIEW=1   previews included (for design review builds)
const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

const config = getDefaultConfig(__dirname);

const production = process.env.NODE_ENV === 'production';
const includePreviews = !production || process.env.EXPO_PUBLIC_DESIGN_PREVIEW === '1';

if (!includePreviews) {
  const escape = (p) => p.replace(/[/\\^$.*+?()[\]{}|]/g, '\\$&');
  const blocked = [path.join(__dirname, 'src', 'app', 'design'), path.join(__dirname, 'src', 'design', 'preview')].map(
    (dir) => new RegExp(`^${escape(dir)}${escape(path.sep)}.*$`),
  );
  const existing = config.resolver.blockList;
  config.resolver.blockList = [...(Array.isArray(existing) ? existing : existing ? [existing] : []), ...blocked];
}

module.exports = config;
