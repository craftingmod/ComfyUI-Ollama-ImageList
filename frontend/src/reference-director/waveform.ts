export type WaveformPairs = ReadonlyArray<readonly [number, number]>;

export function isSilentWaveform(pairs: WaveformPairs | undefined): boolean {
  return pairs !== undefined && pairs.length > 0 && pairs.every(
    ([minimum, maximum]) => minimum === 0 && maximum === 0,
  );
}
