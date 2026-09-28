import { describe, expect, it } from "vitest";
import { eventQueryString } from "../api/client";
import {
  deeplinkFeed,
  feedToParams,
  parseFeed,
  resetPanel,
  toEventQuery,
} from "./feedParams";

describe("feed params", () => {
  it("по умолчанию — официальная лента по дате", () => {
    const f = parseFeed(new URLSearchParams());
    expect(f.tier).toBe("official");
    const query = toEventQuery(f, 7, 30);
    expect(eventQueryString(query)).toBe(
      "locality_id=7&radius_km=30&tier=official&sort=date&limit=20",
    );
  });

  it("туда и обратно без потерь", () => {
    const raw =
      "tier=community&date=weekend&free=1&pushkin=1&cat=music&cat=kids&price_max=500&format=offline&sort=distance&radius=50&q=хор";
    const f = parseFeed(new URLSearchParams(raw));
    expect(feedToParams(f).toString()).toBe(
      new URLSearchParams(raw).toString(),
    );
  });

  it("мусор в параметрах отбрасывается", () => {
    const f = parseFeed(
      new URLSearchParams(
        "tier=all&date=yesterday&radius=7&cat=../x&price_max=-1",
      ),
    );
    expect(f).toMatchObject({
      tier: "official",
      date: null,
      radius: null,
      categories: [],
      priceMax: null,
    });
  });

  it("текстовый поиск сортирует по релевантности, радиус из фильтра важнее профиля", () => {
    const query = toEventQuery(
      parseFeed(new URLSearchParams("q=концерт&radius=50")),
      1,
      15,
    );
    expect(query).toMatchObject({
      q: "концерт",
      sort: "relevance",
      radius_km: 50,
    });
  });

  it("диплинк feed_* превращается в фильтры", () => {
    expect(deeplinkFeed(new URLSearchParams("feed=weekend"))?.toString()).toBe(
      "date=weekend",
    );
    expect(deeplinkFeed(new URLSearchParams("feed=pushkin"))?.toString()).toBe(
      "pushkin=1",
    );
    expect(deeplinkFeed(new URLSearchParams("date=today"))).toBeNull();
  });
});

describe("даты и «для детей»", () => {
  const now = new Date("2026-09-27T22:30:00Z"); // в Москве уже 28-е, в Лондоне ещё 27-е

  it("неделя считается в поясе пункта", () => {
    const f = parseFeed(new URLSearchParams("date=week"));
    expect(toEventQuery(f, 1, 15, "Europe/Moscow", now)).toMatchObject({
      date_from: "2026-09-28",
      date_to: "2026-10-04",
    });
    expect(toEventQuery(f, 1, 15, "Europe/London", now)).toMatchObject({
      date_from: "2026-09-27",
      date_to: "2026-10-03",
    });
    expect(toEventQuery(f, 1, 15, "Europe/Moscow", now).date).toBeUndefined();
  });

  it("свой период: даты в порядке, без дат период снимается", () => {
    const f = parseFeed(new URLSearchParams("date=range&from=2026-10-10&to=2026-10-01"));
    expect(f).toMatchObject({ date: "range", from: "2026-10-01", to: "2026-10-10" });
    expect(toEventQuery(f, 1, 15)).toMatchObject({ date_from: "2026-10-01", date_to: "2026-10-10" });
    expect(parseFeed(new URLSearchParams("date=range&from=вчера")).date).toBeNull();
    expect(parseFeed(new URLSearchParams("date=today&from=2026-10-01")).from).toBeNull();
    expect(feedToParams(f).toString()).toBe("date=range&from=2026-10-01&to=2026-10-10");
  });

  it("для детей — возраст до 6+", () => {
    const f = parseFeed(new URLSearchParams("kids=1"));
    expect(f.kids).toBe(true);
    expect(toEventQuery(f, 1, 15).age).toBe(6);
    expect(feedToParams(f).toString()).toBe("kids=1");
  });

  it("сброс панели снимает свой период, но не быстрые даты", () => {
    const range = parseFeed(new URLSearchParams("date=range&from=2026-10-01"));
    expect(resetPanel(range)).toMatchObject({ date: null, from: null, to: null });
    expect(resetPanel(parseFeed(new URLSearchParams("date=week"))).date).toBe("week");
  });
});
