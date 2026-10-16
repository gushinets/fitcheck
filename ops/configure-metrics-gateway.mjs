import { appendFileSync, readFileSync } from 'node:fs'
import { isIP } from 'node:net'
import { pathToFileURL } from 'node:url'

const hostname = 'dev-fitcheck-api.dokploy.gcexp.ru'

function validateGateway(gateway) {
  if (isIP(gateway) !== 4 || gateway === '0.0.0.0' || gateway === '255.255.255.255') {
    throw new Error('Invalid metrics gateway IPv4 address')
  }
  return gateway
}

export function gatewayFromRoutes(routes) {
  const gateways = new Set()
  for (const line of routes.trim().split('\n')) {
    const fields = line.trim().split(/\s+/)
    if (fields[1] !== '00000000' || fields[7] !== '00000000') continue
    if (!/^[0-9a-f]+$/i.test(fields[3]) || (parseInt(fields[3], 16) & 3) !== 3) continue
    if (!/^[0-9a-f]{8}$/i.test(fields[2])) throw new Error('Malformed metrics gateway route')
    const gateway = fields[2].match(/../g).reverse().map(byte => parseInt(byte, 16)).join('.')
    gateways.add(validateGateway(gateway))
  }
  if (gateways.size !== 1) throw new Error('Expected one unambiguous default metrics gateway')
  return [...gateways][0]
}

export function hostsWithGateway(hosts, gateway) {
  validateGateway(gateway)
  let present = false
  for (const line of hosts.split('\n')) {
    const [address, ...aliases] = line.split('#')[0].trim().split(/\s+/)
    if (!aliases.some(alias => alias.toLowerCase() === hostname)) continue
    if (address !== gateway) throw new Error('Conflicting metrics hostname in /etc/hosts')
    present = true
  }
  if (present) return hosts
  return `${hosts}${hosts && !hosts.endsWith('\n') ? '\n' : ''}${gateway}\t${hostname}\n`
}

// Opt-in only for the verified Dokploy development container topology. Keep
// normal HTTPS hostname verification; never change URLs, credentials or TLS.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href &&
    process.env.FITCHECK_DOKPLOY_METRICS_GATEWAY === 'true') {
  const gateway = gatewayFromRoutes(readFileSync('/proc/net/route', 'utf8'))
  const hosts = readFileSync('/etc/hosts', 'utf8')
  const updated = hostsWithGateway(hosts, gateway)
  if (updated !== hosts) appendFileSync('/etc/hosts', updated.slice(hosts.length))
}
