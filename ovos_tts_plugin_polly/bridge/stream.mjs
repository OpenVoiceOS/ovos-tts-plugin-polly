import { PollyClient, StartSpeechSynthesisStreamCommand } from '@aws-sdk/client-polly';
import { NodeHttp2Handler } from '@smithy/node-http-handler';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';

// Bound newline-delimited input even when the producer omits a newline.
export async function* lines(input) {
  let buffer = Buffer.alloc(0);
  for await (const chunk of input) {
    buffer = Buffer.concat([buffer, chunk]);
    let end;
    while ((end = buffer.indexOf(10)) !== -1) {
      if (end > 65536) throw new Error('Input line too large');
      yield JSON.parse(buffer.subarray(0, end).toString('utf8'));
      buffer = buffer.subarray(end + 1);
    }
    if (buffer.length > 65536) throw new Error('Input line too large');
  }
  if (buffer.length) throw new Error('Incomplete input line');
}

export async function* events(iterator) {
  for await (const value of iterator) {
    if (typeof value.text !== 'string' || !value.text.length) {
      throw new Error('Expected a nonempty text chunk');
    }
    yield { TextEvent: { Text: value.text, TextType: 'text' } };
  }
  yield { CloseStreamEvent: {} };
}

export async function run(input, output, createClient = config => new PollyClient(config)) {
  const iterator = lines(input);
  const { value: header, done } = await iterator.next();
  if (done || header.request?.Engine !== 'generative') {
    throw new Error('The bidirectional API requires the generative engine');
  }
  const client = createClient({
    region: header.region,
    maxAttempts: 1,
    requestHandler: new NodeHttp2Handler({
      requestTimeout: header.timeout_ms ?? 30000,
    }),
  });
  try {
    const response = await client.send(new StartSpeechSynthesisStreamCommand({
      ...header.request, ActionStream: events(iterator),
    }));
    let closed = false;
    for await (const event of response.EventStream) {
      if (event.AudioEvent) {
        if (!output.write(event.AudioEvent.AudioChunk)) await once(output, 'drain');
      } else if (event.StreamClosedEvent) {
        closed = true;
      } else {
        throw new Error('Polly returned a streaming error event');
      }
    }
    if (!closed) throw new Error('Polly stream ended without StreamClosedEvent');
  } finally {
    client.destroy();
    await iterator.return();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run(process.stdin, process.stdout).catch(() => {
    // Do not echo request text, AWS errors, or credentials into application logs.
    process.stderr.write('Polly bidirectional stream failed\n');
    process.exitCode = 1;
    process.stdin.destroy();
  });
}
