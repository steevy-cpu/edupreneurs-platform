// Preflight the endpoints used by the installed test build before touching a device or seed accounts.
const path = require('node:path');
const { deriveRepoTarget, readEnvFile, validateEndpoint } = require('../tests/support/localStack');

function deviceTarget(target, mobile, inherited, hosts) {
  for (const [name, port] of [
    ['EXPO_PUBLIC_API_URL', target.fastApiPort],
    ['EXPO_PUBLIC_SUPABASE_URL', target.apiPort],
  ]) {
    if (mobile[name] && inherited[name] && inherited[name] !== mobile[name]) {
      throw new Error(`Conflicting environment override for ${name}`);
    }
    validateEndpoint(name, inherited[name] ?? mobile[name], 'http:', port, '/', hosts);
  }
  return target;
}

if (require.main === module) {
  const mode = process.argv[2];
  const hosts = mode === 'airplane' ? ['10.0.2.2'] : ['127.0.0.1', 'localhost'];
  if (mode === 'dev') hosts.push('10.0.2.2');
  const target = deviceTarget(deriveRepoTarget(), readEnvFile(path.resolve(__dirname, '../.env.local')), process.env, hosts);
  console.log(target.dbContainer, target.kongContainer, target.fastApiPort, target.apiPort);
}
module.exports = { deviceTarget };
