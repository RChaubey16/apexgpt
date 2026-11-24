/** For tests: an in-memory `Storage`, optionally with a quota (total characters). */
export class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  writes = 0;

  constructor(private quota = Infinity) {}

  get length() {
    return this.data.size;
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null;
  }
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.writes++;
    const others = [...this.data].reduce(
      (n, [k, v]) => (k === key ? n : n + k.length + v.length),
      0,
    );
    if (others + key.length + value.length > this.quota) {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    }
    this.data.set(key, String(value));
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  clear() {
    this.data.clear();
  }
}
