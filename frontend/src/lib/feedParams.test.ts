import { describe, expect, it } from "vitest";
import { eventQueryString } from "../api/client";
import {
  deeplinkFeed,
  feedToParams,
  parseFeed,
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
