// The video's voice-over, one line per shot, spoken by ElevenLabs.
//
//   node --env-file=../../.env.local voice.mjs lines.json <out-dir> [voice-id]
//
// lines.json maps a shot number to its line ({ "02": "The teacher writes..." }); each becomes
// <out-dir>/vo-02.mp3, which the video composer lays under that shot. The API key is read by
// the SDK from ELEVENLABS_API_KEY in the environment (the --env-file above), never from here.
import { ElevenLabsClient } from "@elevenlabs/elevenlabs-js";
import fs from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

// George: a calm narrative voice. Any voice id from the ElevenLabs library works here.
const DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb";

const [, , linesFile, outDir, voiceId = DEFAULT_VOICE] = process.argv;
if (!linesFile || !outDir) {
  console.error("usage: node --env-file=../../.env.local voice.mjs lines.json <out-dir> [voice-id]");
  process.exit(2);
}

const lines = JSON.parse(fs.readFileSync(linesFile, "utf8"));
const shots = Object.keys(lines).filter((k) => lines[k].trim());
fs.mkdirSync(outDir, { recursive: true });

const client = new ElevenLabsClient();
for (const [i, shot] of shots.entries()) {
  const file = path.join(outDir, `vo-${shot}.mp3`);
  const audio = await client.textToSpeech.convert(voiceId, {
    text: lines[shot],
    modelId: "eleven_v4",
    outputFormat: "mp3_44100_128",
    // Narration: steady, with natural variation.
    voiceSettings: { stability: 0.7, similarityBoost: 0.5 },
    // The neighbouring lines, so tone and pauses match across the cuts.
    previousText: i > 0 ? lines[shots[i - 1]] : undefined,
    nextText: i + 1 < shots.length ? lines[shots[i + 1]] : undefined,
  });
  await pipeline(Readable.fromWeb(audio), fs.createWriteStream(file));
  console.log("wrote", file);
}
