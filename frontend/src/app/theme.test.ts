import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function stubBrowser({ dark = false, storage = true }: { dark?: boolean; storage?: boolean } = {}) {
  const store = new Map<string, string>();
  const root = { dataset: {} as Record<string, string> };
  const metas = [{ content: "", setAttribute: (_: string, v: string) => (metas[0].content = v) }];
  const localStorage = {
    getItem: (k: string) => {
      if (!storage) throw new Error("blocked");
      return store.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      if (!storage) throw new Error("blocked");
      store.set(k, v);
    },
    removeItem: (k: string) => store.delete(k),
  };
  vi.stubGlobal("window", { localStorage, matchMedia: () => ({ matches: dark }) });
  vi.stubGlobal("document", { documentElement: root, querySelectorAll: () => metas });
  return { store, root, metas };
}

describe("theme", () => {
  beforeEach(() => vi.resetModules());
  afterEach(() => vi.unstubAllGlobals());

  it("по умолчанию — системная тема", async () => {
    stubBrowser({ dark: true });
    const theme = await import("./theme");
    expect(theme.readPref()).toBe("system");
    expect(theme.resolveTheme("system")).toBe("dark");
  });

  it("выбор сохраняется и ставится на <html data-theme>", async () => {
    const { store, root, metas } = stubBrowser();
    const theme = await import("./theme");
    theme.setThemePref("dark");
    expect(store.get(theme.THEME_KEY)).toBe("dark");
    expect(root.dataset.theme).toBe("dark");
    expect(metas[0].content).toBe("#1b1712");
    theme.setThemePref("system");
    expect(store.has(theme.THEME_KEY)).toBe(false);
    expect(root.dataset.theme).toBe("light");
  });

  it("недоступное хранилище не ломает смену темы", async () => {
    const { root } = stubBrowser({ storage: false });
    const theme = await import("./theme");
    expect(theme.readPref()).toBe("system");
    theme.setThemePref("dark");
    expect(root.dataset.theme).toBe("dark");
  });

  it("мусор в хранилище — системная тема", async () => {
    const { store } = stubBrowser();
    store.set("afisha.theme", "purple");
    const theme = await import("./theme");
    expect(theme.readPref()).toBe("system");
  });
});
