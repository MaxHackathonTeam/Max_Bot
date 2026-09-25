import { afterEach, describe, expect, it, vi } from "vitest";
import {
  isMobileMax,
  openExternal,
  shareContent,
  webShareUrl,
} from "./actions";
import type { WebApp } from "./webApp";

function setWebApp(webApp: WebApp | undefined): void {
  vi.stubGlobal("window", { WebApp: webApp, open: vi.fn() });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("bridge actions", () => {
  it("isMobileMax только для ios/android", () => {
    expect(isMobileMax("ios")).toBe(true);
    expect(isMobileMax("android")).toBe(true);
    expect(isMobileMax("web")).toBe(false);
    expect(isMobileMax("desktop")).toBe(false);
    expect(isMobileMax(undefined)).toBe(false);
  });

  it("webShareUrl кодирует текст со ссылкой", () => {
    const url = webShareUrl("Концерт", "https://max.ru/bot?startapp=ev_1");
    expect(url.startsWith("https://max.ru/:share?text=")).toBe(true);
    expect(new URL(url).searchParams.get("text")).toBe(
      "Концерт\nhttps://max.ru/bot?startapp=ev_1",
    );
  });

  it("openExternal через Bridge, а без него — window.open", () => {
    const openLink = vi.fn();
    setWebApp({ openLink });
    openExternal("https://yandex.ru/maps/?pt=31,58&z=16");
    expect(openLink).toHaveBeenCalledWith(
      "https://yandex.ru/maps/?pt=31,58&z=16",
    );

    setWebApp(undefined);
    openExternal("https://example.org");
    expect(window.open).toHaveBeenCalledWith(
      "https://example.org",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("на телефоне делится через shareMaxContent", async () => {
    const shareMaxContent = vi.fn();
    setWebApp({ platform: "android", shareMaxContent });
    await expect(
      shareContent("Концерт", "https://max.ru/b?startapp=ev_1"),
    ).resolves.toBe("shared");
    expect(shareMaxContent).toHaveBeenCalledWith({
      text: "Концерт",
      link: "https://max.ru/b?startapp=ev_1",
    });
  });

  it("в вебе копирует ссылку, а без буфера открывает max.ru/:share", async () => {
    const shareMaxContent = vi.fn();
    setWebApp({ platform: "web", shareMaxContent });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await expect(
      shareContent("Концерт", "https://max.ru/b?startapp=ev_1"),
    ).resolves.toBe("copied");
    expect(shareMaxContent).not.toHaveBeenCalled();

    vi.stubGlobal("navigator", {});
    await expect(shareContent("Концерт", null)).resolves.toBe("opened");
    expect(window.open).toHaveBeenCalledWith(
      webShareUrl("Концерт"),
      "_blank",
      "noopener,noreferrer",
    );
  });
});
