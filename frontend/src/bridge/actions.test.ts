import { afterEach, describe, expect, it, vi } from "vitest";
import {
  insideMax,
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

  it("openExternal через Bridge в MAX, а без него — window.open", () => {
    const openLink = vi.fn();
    setWebApp({ initData: "signed", openLink });
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

  it("в браузере Bridge без initData не используется: openLink там ничего не делает", () => {
    const openLink = vi.fn();
    setWebApp({ openLink, platform: "web" });
    expect(insideMax()).toBe(false);
    openExternal("https://max.ru/bot?start=login_ABC234");
    expect(openLink).not.toHaveBeenCalled();
    expect(window.open).toHaveBeenCalledWith(
      "https://max.ru/bot?start=login_ABC234",
      "_blank",
      "noopener,noreferrer",
    );

    setWebApp({ initData: "signed", openLink });
    expect(insideMax()).toBe(true);
  });

  const target = {
    text: "Концерт",
    maxLink: "https://max.ru/b?startapp=ev_1",
    webLink: "https://afisha.example/event/1",
  };

  it("в MAX на телефоне делится через shareMaxContent", async () => {
    const shareMaxContent = vi.fn();
    setWebApp({ initData: "signed", platform: "android", shareMaxContent });
    await expect(shareContent(target)).resolves.toBe("shared");
    expect(shareMaxContent).toHaveBeenCalledWith({
      text: "Концерт",
      link: "https://max.ru/b?startapp=ev_1",
    });
  });

  it("в MAX web копирует диплинк, а без буфера открывает max.ru/:share", async () => {
    const shareMaxContent = vi.fn();
    setWebApp({ initData: "signed", platform: "web", shareMaxContent });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await expect(shareContent(target)).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith(target.maxLink);
    expect(shareMaxContent).not.toHaveBeenCalled();

    vi.stubGlobal("navigator", {});
    await expect(shareContent({ ...target, maxLink: null })).resolves.toBe("opened");
    expect(window.open).toHaveBeenCalledWith(
      webShareUrl("Концерт"),
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("в браузере — navigator.share со ссылкой на сайт", async () => {
    setWebApp(undefined);
    const share = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { share });
    await expect(shareContent(target)).resolves.toBe("shared");
    expect(share).toHaveBeenCalledWith({ title: "Концерт", url: target.webLink });

    share.mockRejectedValue(Object.assign(new Error("cancel"), { name: "AbortError" }));
    await expect(shareContent(target)).resolves.toBe("cancelled");
  });

  it("в браузере без share копирует ссылку, без буфера — failed", async () => {
    setWebApp(undefined);
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await expect(shareContent(target)).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith(target.webLink);

    vi.stubGlobal("navigator", {});
    await expect(shareContent(target)).resolves.toBe("failed");
  });
});
