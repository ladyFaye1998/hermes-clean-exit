import * as SDK from '@hermes/plugin-sdk'
import { createElement as h, useEffect, useRef, useState } from 'react'

const ID = 'clean-exit'
const PATH = '/clean-exit'
const RPC = `plugin.${ID}.`

const STATES = {
  present: 'Available',
  archived: 'Archived',
  changed: 'Changed on disk',
  missing: 'Missing',
  conflict: 'Name conflict',
}

const STATE_DETAILS = {
  changed: 'The file differs from the recorded write.',
  missing: 'The recorded file could not be found.',
  conflict: 'A path needed for this file is occupied or unsafe.',
}

const CSS = `
.ce {
  --paper: #f7f8f2;
  --surface: #fff;
  --ink: #222a23;
  --muted: #59645b;
  --line: #dce2d8;
  --sage: #39654b;
  --sage-soft: #e9f1e6;
  --warn: #805723;
  --warn-soft: #fbf0dc;
  --error: #913e35;
  --error-soft: #fbeeea;
  --focus: #77a68a;
  color: var(--ink);
  background: var(--paper);
  font: 14px/1.5 var(--ui-font-sans, 'Segoe UI', system-ui, sans-serif);
  height: 100%;
  min-height: 0;
  overflow: auto;
  container-type: inline-size;
}
.ce * { box-sizing: border-box; }
.ce h1, .ce h2, .ce h3, .ce p, .ce ul { margin: 0; }
.ce button, .ce select { font: inherit; }
.ce button { cursor: pointer; }
.ce button:disabled { cursor: default; opacity: .5; }
.ce button:focus-visible, .ce input:focus-visible, .ce select:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 3px;
}
.ce input[type=checkbox] {
  width: 17px;
  height: 17px;
  margin: 0;
  accent-color: var(--sage);
}
.ce-top {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px clamp(20px, 4vw, 46px);
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.ce-brand, .ce-actions, .ce-file-title { display: flex; align-items: center; gap: 10px; }
.ce-brand strong { font-size: 20px; font-weight: 650; letter-spacing: -.45px; }
.ce-brand-icon {
  width: 37px;
  height: 37px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: var(--sage);
}
.ce-brand-icon .codicon { font-size: 20px; }
.ce-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink);
  padding: 7px 12px;
  font-weight: 600;
  white-space: nowrap;
}
.ce-button:hover:not(:disabled) { background: var(--sage-soft); }
.ce-button-primary { background: var(--sage); border-color: var(--sage); color: #fff; }
.ce-button-primary:hover:not(:disabled) { background: #2e563f; border-color: #2e563f; }
.ce-layout {
  max-width: 1360px;
  margin: 0 auto;
  padding: 36px clamp(20px, 4vw, 46px) 52px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 245px;
  align-items: start;
  gap: 26px;
}
.ce-main { min-width: 0; }
.ce-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 15px;
  overflow: hidden;
}
.ce-hero { padding: clamp(25px, 4vw, 45px); }
.ce-hero h1, .ce-run-head h1, .ce-dialog h2 {
  font-family: Georgia, 'Times New Roman', serif;
  font-weight: 400;
  letter-spacing: -1px;
  line-height: 1.12;
}
.ce-hero h1 { font-size: clamp(32px, 4vw, 51px); }
.ce-hero > p { color: var(--muted); max-width: 48ch; margin: 13px 0 21px; }
.ce-folder {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--line);
  background: var(--sage-soft);
  border-radius: 10px;
  padding: 12px;
  margin: 20px 0 16px;
}
.ce-folder > div { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.ce-folder small, .ce-subtle { color: var(--muted); }
.ce-field { display: block; margin: 16px 0; }
.ce-field > span { display: block; margin-bottom: 6px; font-weight: 600; }
.ce-field select {
  width: min(100%, 420px);
  min-height: 38px;
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
}
.ce-help { font-size: 12px; margin: 8px 0 18px !important; color: var(--muted); }
.ce-alert {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 13px;
  border-radius: 9px;
  margin-bottom: 13px;
  overflow-wrap: anywhere;
}
.ce-alert > span:nth-child(2) { flex: 1; }
.ce-error { background: var(--error-soft); color: var(--error); }
.ce-notice { background: var(--sage-soft); color: var(--sage); }
.ce-alert > .codicon { margin-top: 3px; }
.ce-dismiss { border: 0; background: transparent; color: inherit; padding: 1px 3px; }
.ce-run-head { padding: 27px 25px 21px; border-bottom: 1px solid var(--line); }
.ce-run-head h1 { font-size: clamp(27px, 3.5vw, 40px); overflow-wrap: anywhere; margin-top: 7px; }
.ce-run-head .ce-subtle { margin-top: 7px; }
.ce-run-head-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }
.ce-run-head-row > div { min-width: 0; }
.ce-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--sage-soft);
  color: var(--sage);
  border-radius: 6px;
  padding: 4px 7px;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}
.ce-pill-changed, .ce-pill-missing, .ce-pill-conflict { background: var(--warn-soft); color: var(--warn); }
.ce-pill-archived { background: var(--paper); color: var(--muted); }
.ce-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.ce-list { list-style: none; padding: 0; }
.ce-row {
  display: grid;
  grid-template-columns: 25px minmax(0, 1fr) auto 82px;
  gap: 12px;
  align-items: center;
  padding: 14px 24px;
  border-bottom: 1px solid var(--line);
  min-height: 67px;
}
.ce-row:last-child { border-bottom: 0; }
.ce-row-selected { background: var(--sage-soft); }
.ce-file-title { font-weight: 600; min-width: 0; align-items: baseline; }
.ce-file-title .codicon { color: var(--sage); }
.ce-file-path { overflow-wrap: anywhere; }
.ce-file-detail { display: block; color: var(--muted); font-size: 11px; margin: 3px 0 0 25px; }
.ce-file-state { justify-self: start; }
.ce-row .ce-button { min-height: 30px; padding: 4px 9px; font-size: 12px; }
.ce-footer {
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 24px;
  color: var(--muted);
}
.ce-empty { color: var(--muted); padding: 29px 25px; }
.ce-history h2 { font-size: 14px; font-weight: 650; margin: 0 0 12px; }
.ce-history > p { color: var(--muted); font-size: 12px; }
.ce-history-list { display: flex; flex-direction: column; gap: 7px; list-style: none; padding: 0; }
.ce-history-item {
  width: 100%;
  text-align: left;
  display: flex;
  align-items: flex-start;
  gap: 9px;
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 10px;
}
.ce-history-item[aria-current=true], .ce-history-item:hover:not(:disabled) {
  background: var(--sage-soft);
  border-color: var(--focus);
}
.ce-history-item .codicon { margin-top: 3px; color: var(--sage); }
.ce-history-item strong { font-size: 12px; overflow-wrap: anywhere; }
.ce-history-item small { display: block; font-size: 11px; color: var(--muted); }
.ce-dialog {
  width: min(500px, calc(100% - 24px));
  max-height: calc(100% - 32px);
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 25px;
}
.ce-dialog::backdrop { background: #16251c67; }
.ce-dialog h2 { font-size: 31px; }
.ce-dialog p { color: var(--muted); margin: 9px 0 13px; }
.ce-dialog ul { max-height: 220px; overflow: auto; padding: 9px 8px 9px 27px; background: var(--paper); border-radius: 8px; }
.ce-dialog li { padding: 3px 0; overflow-wrap: anywhere; }
.ce-dialog .ce-actions { justify-content: flex-end; margin-top: 17px; }
@container (max-width: 780px) {
  .ce-layout { grid-template-columns: minmax(0, 1fr); }
  .ce-history-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); }
}
@container (max-width: 520px) {
  .ce-top { padding: 12px 15px; flex-wrap: wrap; }
  .ce-layout { padding: 22px 13px 35px; }
  .ce-run-head, .ce-footer { padding: 15px; }
  .ce-run-head-row, .ce-footer { flex-wrap: wrap; }
  .ce-row { grid-template-columns: 21px minmax(0, 1fr) auto; padding: 11px 13px; gap: 8px; }
  .ce-file-state { grid-column: 2; }
  .ce-restore { grid-column: 3; grid-row: 1 / span 2; }
}
@media (prefers-color-scheme: dark) {
  .ce {
    --paper: #202720;
    --surface: #28312a;
    --ink: #ecf2eb;
    --muted: #b5c3b7;
    --line: #425246;
    --sage: #89b99a;
    --sage-soft: #304638;
    --warn: #e0bf89;
    --warn-soft: #463922;
    --error: #f0b3ab;
    --error-soft: #51322f;
  }
  .ce-button-primary, .ce-brand-icon { color: #16251c; }
  .ce-button-primary:hover:not(:disabled) { color: #fff; }
}
`

function Icon({ name }) {
  return h('span', { className: `codicon codicon-${name}`, 'aria-hidden': true })
}

function Button({ primary, icon, children, className = '', ...props }) {
  const classes = ['ce-button', primary && 'ce-button-primary', className].filter(Boolean).join(' ')
  return h('button', { type: 'button', className: classes, ...props }, icon && h(Icon, { name: icon }), children)
}

function formatBytes(size) {
  if (!Number.isFinite(size) || size < 0) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function errorMessage(error) {
  return error?.message || error?.detail || String(error || 'The request could not be completed.')
}

function scopeStamp(host) {
  const profile = host.state.profile.get()
  const owner = host.state.focusedSessionOwner?.get()
  const epoch = SDK.gatewayActivationEpoch?.() ?? 0
  return JSON.stringify([epoch, profile, owner?.connectionId || '', owner?.profile || ''])
}

async function getLocalScope(host) {
  if (typeof host.profileRoutes !== 'function' || typeof host.requestProfile !== 'function') {
    throw new Error('Update Hermes Desktop to use local profile routing.')
  }
  const stamp = scopeStamp(host)
  const owner = host.state.focusedSessionOwner?.get()
  const profile = host.state.profile.get()
  const routes = await host.profileRoutes()
  if (stamp !== scopeStamp(host)) throw new Error('The Hermes connection changed. Refresh to continue.')
  const matches = routes.filter(route => owner
    ? route.connectionId === owner.connectionId && route.profile === owner.profile
    : route.profile === profile)
  if (matches.length !== 1 || matches[0].mode !== 'local') {
    throw new Error('Open a local Hermes profile to track files on this computer.')
  }
  return { stamp, route: matches[0] }
}

async function request(host, scope, method, params = {}, foreground = false) {
  if (scope.stamp !== scopeStamp(host)) throw new Error('The Hermes connection changed. Refresh to continue.')
  const result = await host.requestProfile(scope.route, method, params, undefined,
    { spawnPriority: foreground ? 'foreground' : 'background' })
  if (scope.stamp !== scopeStamp(host)) throw new Error('The Hermes connection changed during the request.')
  return result
}

function StatusNote({ error, message, clear }) {
  return h('div', { className: `ce-alert ${error ? 'ce-error' : 'ce-notice'}`, role: error ? 'alert' : 'status' },
    h(Icon, { name: error ? 'warning' : 'check' }),
    h('span', null, message),
    h('button', { type: 'button', className: 'ce-dismiss', 'aria-label': 'Dismiss message', onClick: clear },
      h(Icon, { name: 'close' })))
}

function ArchiveDialog({ run, files, busy, onCancel, onConfirm }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return h('dialog', {
    ref,
    className: 'ce-dialog',
    'aria-labelledby': 'ce-archive-title',
    onCancel: event => {
      event.preventDefault()
      if (!busy) onCancel()
    },
  },
  h('h2', { id: 'ce-archive-title' }, `Archive ${files.length} file${files.length === 1 ? '' : 's'}?`),
  h('p', null, `Move these files into the .clean-exit archive in ${run.folderName}. You can restore each file from this run.`),
  h('ul', null, files.map(file => h('li', { key: file.id }, file.path))),
  h('div', { className: 'ce-actions' },
    h(Button, { onClick: onCancel, disabled: busy, autoFocus: true }, 'Cancel'),
    h(Button, { primary: true, icon: 'archive', disabled: busy || !files.length, onClick: onConfirm },
      busy ? 'Archiving…' : 'Archive files')))
}

function FileRow({ file, tracking, selected, disabled, onSelect, onRestore }) {
  const selectable = !tracking && file.state === 'present'
  const detail = [formatBytes(file.size), STATE_DETAILS[file.state]].filter(Boolean).join(' · ')
  return h('li', { className: `ce-row${selected ? ' ce-row-selected' : ''}` },
    selectable ? h('input', {
      type: 'checkbox', checked: selected, disabled, onChange: event => onSelect(file.id, event.target.checked),
      'aria-label': `Select ${file.path} for archive`,
    }) : h('span', { 'aria-hidden': true }),
    h('div', null,
      h('div', { className: 'ce-file-title' }, h(Icon, { name: 'file' }), h('span', { className: 'ce-file-path' }, file.path)),
      detail && h('small', { className: 'ce-file-detail' }, detail)),
    h('span', { className: `ce-file-state ce-pill ce-pill-${file.state}` },
      tracking && file.state === 'present' ? 'Recorded' : STATES[file.state] || 'Unknown state'),
    !tracking && file.state === 'archived' && h(Button, {
      className: 'ce-restore', disabled, icon: 'discard', 'aria-label': `Restore ${file.path}`, onClick: () => onRestore(file),
    }, 'Restore'))
}

function CleanExit({ ctx }) {
  const host = ctx.host || SDK.host
  const [runs, setRuns] = useState([])
  const [runId, setRunId] = useState('')
  const [folder, setFolder] = useState(null)
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState('')
  const [selected, setSelected] = useState([])
  const [confirmation, setConfirmation] = useState(null)
  const [busy, setBusy] = useState('')
  const [loading, setLoading] = useState(true)
  const [localReady, setLocalReady] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const state = useRef({ mounted: false, serial: 0, scope: null, reading: false, busy: false, tracking: false, nextPoll: 0 })

  function publish(result, preferredId) {
    if (!Array.isArray(result?.runs)) throw new Error('Clean Exit returned an invalid run list.')
    const next = result.runs
    state.current.tracking = next.some(item => item.status === 'tracking')
    setRuns(next)
    setRunId(current => {
      if (preferredId && next.some(item => item.id === preferredId)) return preferredId
      if (next.some(item => item.id === current)) return current
      return next.find(item => item.status === 'tracking')?.id || next[0]?.id || ''
    })
  }

  async function refresh({ initial = false, foreground = false } = {}) {
    const control = state.current
    if (control.reading || control.busy) return
    const serial = ++control.serial
    control.reading = true
    control.nextPoll = Date.now() + 2300
    if (initial) setLoading(true)
    if (foreground) setError('')
    try {
      let scope = control.scope
      if (!scope || scope.stamp !== scopeStamp(host)) scope = await getLocalScope(host)
      const result = await request(host, scope, `${RPC}status`, {}, foreground)
      if (!control.mounted || control.serial !== serial) return
      control.scope = scope
      setLocalReady(true)
      publish(result)
    } catch (err) {
      if (!control.mounted || control.serial !== serial) return
      if (!control.scope || control.scope.stamp !== scopeStamp(host)) setLocalReady(false)
      setError(errorMessage(err))
    } finally {
      if (control.mounted && control.serial === serial) {
        control.reading = false
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    const control = state.current
    control.mounted = true
    let stamp = scopeStamp(host)
    refresh({ initial: true })
    const stop = ctx.setInterval(() => {
      const currentStamp = scopeStamp(host)
      if (currentStamp !== stamp) {
        stamp = currentStamp
        control.serial++
        control.scope = null
        control.reading = false
        control.busy = false
        control.tracking = false
        setRuns([])
        setRunId('')
        setFolder(null)
        setSelected([])
        setConfirmation(null)
        setBusy('')
        setLocalReady(false)
        setError('')
        setNotice('')
        refresh({ initial: true })
      } else if (control.tracking && Date.now() >= control.nextPoll) {
        refresh()
      }
    }, 1000)
    return () => {
      control.mounted = false
      control.serial++
      control.reading = false
      stop()
    }
  }, [ctx, host])

  useEffect(() => {
    setSelected([])
    setConfirmation(null)
  }, [runId])

  async function perform(label, action, refreshOnError = true) {
    const control = state.current
    if (control.busy || !control.scope) return
    const scope = control.scope
    if (scope.stamp !== scopeStamp(host)) {
      setError('The Hermes connection changed. Refresh before continuing.')
      return
    }
    const serial = ++control.serial
    control.busy = true
    control.reading = false
    setBusy(label)
    setError('')
    setNotice('')
    try {
      await action(scope)
    } catch (err) {
      if (!control.mounted || control.serial !== serial) return
      setError(errorMessage(err))
      if (refreshOnError && scope.stamp === scopeStamp(host)) {
        try {
          const result = await request(host, scope, `${RPC}status`)
          if (control.mounted && control.serial === serial) publish(result)
        } catch {
          // Preserve the action error. The user can refresh after reconnecting.
        }
      }
    } finally {
      if (control.mounted && control.serial === serial) {
        control.busy = false
        setBusy('')
      }
    }
  }

  function chooseFolder() {
    return perform('folder', async scope => {
      if (!ctx.files?.requestFolder) throw new Error('Folder access requires Hermes Desktop.')
      const pick = await ctx.files.requestFolder()
      if (scope.stamp !== scopeStamp(host)) throw new Error('The Hermes connection changed. Choose the folder again.')
      if (!pick.ok) throw new Error(pick.message || 'The folder could not be opened.')
      if (!pick.folder) return
      if (!/^[A-Za-z]:[\\/]/.test(pick.folder.path || '')) throw new Error('Choose a local Windows folder.')

      const owner = host.state.focusedSessionOwner?.get()
      const focused = owner?.connectionId === scope.route.connectionId && owner?.profile === scope.route.profile
        ? host.state.focusedStoredSessionId?.get() : null
      let saved = []
      try {
        const result = await request(host, scope, 'session.list', { limit: 20 })
        saved = (result?.sessions || []).filter(item => item.id && !item.parent_session_id && item.source !== 'tool')
      } catch {
        // An unavailable session list still permits the documented first-write mode.
      }
      if (scope.stamp !== scopeStamp(host)) throw new Error('The Hermes connection changed. Choose the folder again.')
      if (focused && !saved.some(item => item.id === focused)) saved.unshift({ id: focused, title: 'Focused session' })
      setSessions(saved)
      setSessionId(focused || '')
      setFolder({ ...pick.folder, scope: scope.stamp })
    }, false)
  }

  function startTracking() {
    return perform('start', async scope => {
      if (!folder || folder.scope !== scope.stamp) throw new Error('Choose the folder again for this Hermes connection.')
      const params = { folder: folder.path }
      if (sessionId) params.sessionId = sessionId
      const result = await request(host, scope, `${RPC}start`, params, true)
      publish(result, result.runs?.find(item => item.status === 'tracking')?.id)
      setFolder(null)
      setSelected([])
    })
  }

  const active = runs.find(item => item.status === 'tracking')
  const run = runs.find(item => item.id === runId)
  const tracking = run?.status === 'tracking'
  const files = run?.files || []
  const pickedFiles = files.filter(file => file.state === 'present' && selected.includes(file.id))
  const archivedCount = files.filter(file => file.state === 'archived').length

  function finishTracking() {
    return perform('finish', async scope => {
      const result = await request(host, scope, `${RPC}finish`, { runId: run.id }, true)
      publish(result, run.id)
    })
  }

  function archiveFiles() {
    const chosen = confirmation?.files || []
    setConfirmation(null)
    return perform('archive', async scope => {
      const result = await request(host, scope, `${RPC}archive`, { runId: run.id, fileIds: chosen.map(file => file.id) }, true)
      publish(result, run.id)
      const updated = result.runs.find(item => item.id === run.id)?.files || []
      const count = updated.filter(file => file.state === 'archived' && chosen.some(item => item.id === file.id)).length
      if (count) setNotice(`Archived ${count} file${count === 1 ? '' : 's'}.`)
      setSelected([])
    })
  }

  function restoreFile(file) {
    return perform('restore', async scope => {
      const result = await request(host, scope, `${RPC}restore`, { runId: run.id, fileIds: [file.id] }, true)
      publish(result, run.id)
      const restored = result.runs.find(item => item.id === run.id)?.files.find(item => item.id === file.id)
      if (restored?.state === 'present') setNotice(`Restored ${file.path}.`)
    })
  }

  function openRun(id) {
    setFolder(null)
    setRunId(id)
    setError('')
    setNotice('')
  }

  function openFolder() {
    return perform('reveal', async () => {
      if (!(await ctx.os?.revealPath?.(run.folder))) throw new Error('The folder could not be opened in Explorer.')
    }, false)
  }

  function selectFile(id, checked) {
    setSelected(current => checked ? [...current.filter(item => item !== id), id] : current.filter(item => item !== id))
  }

  const empty = h('section', { className: 'ce-card ce-hero' },
    h('h1', null, 'Choose a folder to track'),
    h('p', null, 'Review new files written during one Hermes run. Keep the deliverable and archive the scratch files you select.'),
    h(Button, { primary: true, icon: 'folder-opened', onClick: chooseFolder, disabled: !localReady || !!busy },
      busy === 'folder' ? 'Opening…' : 'Choose folder'))

  const setup = folder && h('section', { className: 'ce-card ce-hero' },
    h('h1', null, 'Start tracking'),
    h('div', { className: 'ce-folder' },
      h(Icon, { name: 'folder' }),
      h('div', { title: folder.path }, h('small', null, 'Selected folder'), h('div', null, folder.name)),
      h(Button, { onClick: chooseFolder, disabled: !!busy }, 'Change folder')),
    h('label', { className: 'ce-field' },
      h('span', null, 'Session'),
      h('select', { value: sessionId, disabled: !!busy, onChange: event => setSessionId(event.target.value) },
        h('option', { value: '' }, 'First matching write'),
        sessions.map(item => h('option', { key: item.id, value: item.id }, item.title || `Session ${item.id.slice(-8)}`)))),
    h('p', { className: 'ce-help' }, sessionId
      ? 'Track observed new writes from this session in the selected folder.'
      : 'The first session that successfully writes a new file here will be tracked.'),
    h('div', { className: 'ce-actions' },
      h(Button, { primary: true, icon: 'play', disabled: !!busy || !!active, onClick: startTracking },
        busy === 'start' ? 'Starting…' : 'Start tracking'),
      h(Button, { disabled: !!busy, onClick: () => setFolder(null) }, 'Cancel')))

  const review = run && h('section', { className: 'ce-card' },
    h('header', { className: 'ce-run-head' },
      h('div', { className: 'ce-run-head-row' },
        h('div', null,
          h('span', { className: 'ce-pill' }, tracking && h('span', { className: 'ce-dot' }), tracking ? 'Tracking' : 'Review'),
          h('h1', { title: run.folder }, run.folderName),
          h('p', { className: 'ce-subtle' }, tracking
            ? `${files.length} observed ${files.length === 1 ? 'file' : 'files'}`
            : 'Select only the files you want to archive.')),
        h('div', { className: 'ce-actions' },
          typeof ctx.os?.revealPath === 'function' && h(Button, { icon: 'folder-opened', disabled: !!busy, onClick: openFolder }, 'Open folder'),
          tracking && h(Button, { primary: true, icon: 'check', disabled: !!busy, onClick: finishTracking },
            busy === 'finish' ? 'Finishing…' : 'Finish tracking')))),
    files.length ? h('ul', { className: 'ce-list', 'aria-label': 'Files observed during this run' }, files.map(file => h(FileRow, {
      key: file.id, file, tracking, selected: pickedFiles.some(item => item.id === file.id),
      disabled: !!busy, onSelect: selectFile, onRestore: restoreFile,
    }))) : h('p', { className: 'ce-empty' }, tracking ? 'Waiting for a new write in this folder.' : 'No new writes were recorded in this run.'),
    !tracking && h('footer', { className: 'ce-footer' },
      h('span', null, `${pickedFiles.length} selected · ${archivedCount} archived`),
      h(Button, { primary: true, icon: 'archive', disabled: !!busy || !pickedFiles.length,
        onClick: () => setConfirmation({ files: pickedFiles }) }, 'Archive selected')))

  return h('div', { className: 'ce' },
    h('style', null, CSS),
    h('header', { className: 'ce-top' },
      h('div', { className: 'ce-brand' }, h('span', { className: 'ce-brand-icon' }, h(Icon, { name: 'archive' })), h('strong', null, 'Clean Exit')),
      h('div', { className: 'ce-actions' },
        h(Button, { icon: 'refresh', disabled: !!busy, onClick: () => refresh({ foreground: true }) }, 'Refresh'),
        !active && runs.length > 0 && !folder && h(Button, { icon: 'folder-opened', onClick: chooseFolder, disabled: !localReady || !!busy }, 'Choose folder'))),
    h('div', { className: 'ce-layout' },
      h('main', { className: 'ce-main' },
        error && h(StatusNote, { error: true, message: error, clear: () => setError('') }),
        notice && h(StatusNote, { message: notice, clear: () => setNotice('') }),
        loading ? h('p', { className: 'ce-empty', role: 'status' }, 'Opening Clean Exit…') : setup || review || empty),
      h('aside', { className: 'ce-history', 'aria-label': 'Previous runs' },
        h('h2', null, 'Previous runs'),
        runs.length ? h('ul', { className: 'ce-history-list' }, runs.map(item => h('li', { key: item.id },
          h('button', { type: 'button', className: 'ce-history-item', 'aria-current': !folder && item.id === runId, disabled: !!busy,
            onClick: () => openRun(item.id) },
          h(Icon, { name: item.status === 'tracking' ? 'record' : 'history' }),
          h('span', null,
            h('strong', null, item.folderName),
            h('small', null, `${item.status === 'tracking' ? 'Tracking' : 'Review'} · ${item.files.length} ${item.files.length === 1 ? 'file' : 'files'}`))))))
          : h('p', null, 'No previous runs.'))),
    confirmation && run && h(ArchiveDialog, {
      run, files: confirmation.files, busy: !!busy,
      onCancel: () => setConfirmation(null), onConfirm: archiveFiles,
    }))
}

export default {
  id: ID,
  name: 'Clean Exit',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: SDK.ROUTES_AREA, data: { path: PATH }, render: () => h(CleanExit, { ctx }) },
      { id: 'nav', area: SDK.SIDEBAR_NAV_AREA, data: { path: PATH, label: 'Clean Exit', codicon: 'archive' }, order: 66 },
    ])
  },
}
