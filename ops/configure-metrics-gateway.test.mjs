// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { gatewayFromRoutes, hostsWithGateway } from './configure-metrics-gateway.mjs'

const header = 'Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n'
const route = (gateway = '010012AC', flags = '0003') => `eth0 00000000 ${gateway} ${flags} 0 0 0 00000000 0 0 0\n`
const hostname = 'dev-fitcheck-api.dokploy.gcexp.ru'

describe('opt-in Dokploy metrics gateway', () => {
  it('decodes a Linux default gateway in little-endian order', () => {
    expect(gatewayFromRoutes(header + 'eth0 000012AC 00000000 0001 0 0 0 0000FFFF 0 0 0\n' + route())).toBe('172.18.0.1')
    expect(gatewayFromRoutes(header + route('0100A8C0'))).toBe('192.168.0.1')
  })
  it('fails closed for absent, inactive, malformed or ambiguous gateways', () => {
    for (const routes of [header, route('010012AC', '0000'), route('oops'), route('00000000'), route('FFFFFFFF'), route() + route('010013AC')]) {
      expect(() => gatewayFromRoutes(routes)).toThrow()
    }
    expect(gatewayFromRoutes(route() + route())).toBe('172.18.0.1')
  })
  it('preserves all existing hosts content and appends only the hardcoded hostname', () => {
    const original = '127.0.0.1 localhost\n::1 localhost ip6-localhost\n10.0.0.2 unrelated # keep'
    const updated = hostsWithGateway(original, '172.18.0.1')
    expect(updated).toBe(`${original}\n172.18.0.1\t${hostname}\n`)
    expect(hostsWithGateway(updated, '172.18.0.1')).toBe(updated)
    expect(hostsWithGateway(`172.18.0.1 alias ${hostname.toUpperCase()} # keep\n`, '172.18.0.1')).toBe(`172.18.0.1 alias ${hostname.toUpperCase()} # keep\n`)
  })
  it('rejects conflicting aliases, including after an existing correct entry', () => {
    for (const hosts of [`10.0.0.2 ${hostname}\n`, `172.18.0.1 ${hostname}\n10.0.0.2 alias ${hostname}\n`]) {
      expect(() => hostsWithGateway(hosts, '172.18.0.1')).toThrow('Conflicting')
    }
    expect(() => hostsWithGateway('', 'not-an-ip')).toThrow('Invalid')
  })
  it('runs safely as a no-op unless the opt-in is exactly true', () => {
    for (const flag of ['', 'false', 'TRUE']) {
      const result = spawnSync(process.execPath, ['ops/configure-metrics-gateway.mjs'], { env: { ...process.env, FITCHECK_DOKPLOY_METRICS_GATEWAY: flag } })
      expect(result.status, result.stderr.toString()).toBe(0)
    }
  })
  it('checks shell syntax and runs helper before exec pnpm with exact arguments', () => {
    expect(spawnSync('/bin/sh', ['-n', 'ops/dokploy-website-start.sh']).status).toBe(0)
    const directory = mkdtempSync(join(tmpdir(), 'fitcheck-start-'))
    try {
      const log = join(directory, 'calls')
      writeFileSync(join(directory, 'node'), '#!/bin/sh\nprintf "helper:%s\\n" "$*" >> "$STARTUP_TEST_LOG"\nexit "${HELPER_TEST_EXIT:-0}"\n', { mode: 0o755 })
      writeFileSync(join(directory, 'pnpm'), '#!/bin/sh\nprintf "pnpm:%s pid:%s\\n" "$*" "$$" >> "$STARTUP_TEST_LOG"\nexit 23\n', { mode: 0o755 })
      const env = { ...process.env, PATH: directory, STARTUP_TEST_LOG: log, HELPER_TEST_EXIT: '0' }
      const result = spawnSync('/bin/sh', ['ops/dokploy-website-start.sh'], { env })
      expect(result.status).toBe(23)
      expect(readFileSync(log, 'utf8')).toBe(`helper:ops/configure-metrics-gateway.mjs\npnpm:run start pid:${result.pid}\n`)
      writeFileSync(log, '')
      const failed = spawnSync('/bin/sh', ['ops/dokploy-website-start.sh'], { env: { ...env, HELPER_TEST_EXIT: '7' } })
      expect(failed.status).toBe(7)
      expect(readFileSync(log, 'utf8')).toBe('helper:ops/configure-metrics-gateway.mjs\n')
    } finally { rmSync(directory, { recursive: true, force: true }) }
  })
})
