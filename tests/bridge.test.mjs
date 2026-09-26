import assert from 'node:assert/strict';
import test from 'node:test';
import { Readable, Writable } from 'node:stream';
import { events, lines, run } from '../ovos_tts_plugin_polly/bridge/stream.mjs';

const input = (...values) => Readable.from(values.map(v => Buffer.from(JSON.stringify(v) + '\n')));

test('text events preserve French and close exactly once', async () => {
  const result = [];
  for await (const event of events(lines(input({text: 'État du serveur.'})))) result.push(event);
  assert.deepEqual(result, [
    {TextEvent: {Text: 'État du serveur.', TextType: 'text'}}, {CloseStreamEvent: {}},
  ]);
});

test('HTTP/2 request streams input and output and destroys client', async () => {
  let destroyed = false;
  let received = 0;
  const data = [];
  const output = new Writable({ highWaterMark: 1, write(chunk, encoding, callback) {
    data.push(chunk); setImmediate(callback);
  }});
  await run(input({region: 'us-east-1', request: {Engine: 'generative', VoiceId: 'Tiffany', OutputFormat: 'mp3'}},
    {text: 'Hello'}, {text: ' world'}), output, config => {
    assert.equal(config.maxAttempts, 1);
    return {
      async send(command) {
        assert.equal(command.input.VoiceId, 'Tiffany');
        return {EventStream: (async function* () {
          for await (const event of command.input.ActionStream) {
            received++;
            if (event.TextEvent) yield {AudioEvent: {AudioChunk: Buffer.from(event.TextEvent.Text)}};
            else yield {StreamClosedEvent: {RequestCharacters: 11}};
          }
        })()};
      },
      destroy() {destroyed = true;},
    };
  });
  assert.equal(Buffer.concat(data).toString(), 'Hello world');
  assert.equal(received, 3);
  assert.ok(destroyed);
});

test('service error events fail and close client', async () => {
  let destroyed = false;
  await assert.rejects(run(input({request: {Engine: 'generative'}}), new Writable(), () => ({
    async send() {return {EventStream: (async function* () {yield {ThrottlingException: {}};})()};},
    destroy() {destroyed = true;},
  })), /streaming error/);
  assert.ok(destroyed);
});

test('unterminated and oversized input are rejected', async () => {
  for (const text of ['{"text":"hello"}', 'a'.repeat(65537)]) {
    await assert.rejects(async () => { for await (const _ of lines(Readable.from([Buffer.from(text)]))) void _; });
  }
});

test('missing terminal event is an incomplete response', async () => {
  await assert.rejects(run(input({request: {Engine: 'generative'}}), new Writable({write(c,e,cb){cb();}}), () => ({
    async send() {return {EventStream: (async function* () {yield {AudioEvent: {AudioChunk: Buffer.from('a')}};})()};},
    destroy() {},
  })), /without StreamClosedEvent/);
});
