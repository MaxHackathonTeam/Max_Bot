import { Button, Input, Textarea, Typography } from "@maxhub/max-ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import type { Locality } from "../api/client";
import {
  lookupInn,
  ORG_KINDS,
  type Org,
  type OrgInput,
  type OrgKind,
} from "../api/organizer";
import { Chip } from "./Chip";
import { FormErrors } from "./FormErrors";
import { LocalityPicker } from "./LocalityPicker";

const INN = /^(\d{10}|\d{12})$/;

/** Создание и правка организации; ИНН заполняет название и адрес из реестра (DaData). */
export function OrgForm({
  initial,
  busy,
  error,
  submitLabel,
  onSubmit,
}: {
  initial?: Org;
  busy: boolean;
  error: Error | null;
  submitLabel: string;
  onSubmit: (body: OrgInput) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<OrgKind>(initial?.kind ?? "dk");
  const [inn, setInn] = useState(initial?.inn ?? "");
  const [address, setAddress] = useState(initial?.address ?? "");
  const [website, setWebsite] = useState(initial?.website ?? "");
  const [phone, setPhone] = useState(initial?.phone ?? "");
  const [email, setEmail] = useState(initial?.email ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [locality, setLocality] = useState<{ id: number; name: string } | null>(
    initial?.locality_id
      ? { id: initial.locality_id, name: initial.locality_name ?? "" }
      : null,
  );
  const [picking, setPicking] = useState(false);

  const lookup = useMutation({
    mutationFn: () => lookupInn(inn.trim()),
    onSuccess: (found) => {
      if (!found.found) return;
      if (found.name) setName(found.name);
      if (found.address) setAddress(found.address);
      if (found.kind === "individual") setKind("ip");
    },
  });

  const problems: string[] = [];
  if (name.trim().length < 2) problems.push("Название — хотя бы 2 символа");
  if (inn.trim() && !INN.test(inn.trim()))
    problems.push("ИНН — 10 или 12 цифр");
  if (website.trim() && !/^https:\/\/\S+$/.test(website.trim()))
    problems.push("Сайт — ссылка https://");

  const submit = () =>
    onSubmit({
      name: name.trim(),
      kind,
      inn: inn.trim() || null,
      locality_id: locality?.id ?? null,
      address: address.trim() || null,
      website: website.trim() || null,
      phone: phone.trim() || null,
      email: email.trim() || null,
      description: description.trim() || null,
    });

  return (
    <div className="stack">
      <Typography.Label variant="medium-strong">
        ИНН (заполнит название и адрес)
      </Typography.Label>
      <div className="row">
        <Input
          inputMode="numeric"
          placeholder="10 или 12 цифр"
          value={inn}
          onChange={(e) =>
            setInn(e.target.value.replace(/\D/g, "").slice(0, 12))
          }
          aria-label="ИНН"
        />
        <Button
          size="medium"
          variant="secondary"
          disabled={!INN.test(inn.trim())}
          loading={lookup.isPending}
          onClick={() => lookup.mutate()}
        >
          Найти
        </Button>
      </div>
      {lookup.data && !lookup.data.found && (
        <Typography.Body variant="small" className="muted">
          В реестре не нашлось — заполни вручную.
        </Typography.Body>
      )}
      {lookup.data?.found && (
        <Typography.Body variant="small" className="muted">
          Нашли: {lookup.data.name}
          {lookup.data.status && lookup.data.status !== "ACTIVE"
            ? ` · статус ${lookup.data.status}`
            : ""}
        </Typography.Body>
      )}
      <FormErrors error={lookup.error} />

      <Typography.Label variant="medium-strong">Название</Typography.Label>
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={255}
        aria-label="Название"
      />

      <Typography.Label variant="medium-strong">Тип</Typography.Label>
      <div className="chips chips--wrap">
        {ORG_KINDS.map((k) => (
          <Chip
            key={k.value}
            selected={kind === k.value}
            onClick={() => setKind(k.value)}
          >
            {k.label}
          </Chip>
        ))}
      </div>

      <Typography.Label variant="medium-strong">
        Населённый пункт
      </Typography.Label>
      {picking ? (
        <LocalityPicker
          onPick={(l: Locality) => {
            setLocality({ id: l.id, name: l.name });
            setPicking(false);
          }}
        />
      ) : (
        <Button
          size="medium"
          variant="secondary"
          onClick={() => setPicking(true)}
        >
          {locality ? `📍 ${locality.name}` : "Выбрать"}
        </Button>
      )}

      <Typography.Label variant="medium-strong">Адрес</Typography.Label>
      <Input
        value={address}
        onChange={(e) => setAddress(e.target.value)}
        maxLength={500}
        aria-label="Адрес"
      />
      <Typography.Label variant="medium-strong">
        Сайт или страница ВК
      </Typography.Label>
      <Input
        value={website}
        placeholder="https://"
        onChange={(e) => setWebsite(e.target.value)}
        aria-label="Сайт"
      />
      <Typography.Label variant="medium-strong">
        Телефон и e-mail организации
      </Typography.Label>
      <Input
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        maxLength={32}
        aria-label="Телефон"
      />
      <Input
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        maxLength={255}
        aria-label="E-mail"
      />
      <Typography.Label variant="medium-strong">
        Коротко об организации
      </Typography.Label>
      <Textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        maxLength={2000}
        aria-label="Описание"
      />

      <FormErrors error={error} />
      <Button
        size="large"
        stretched
        disabled={problems.length > 0}
        loading={busy}
        onClick={submit}
      >
        {submitLabel}
      </Button>
      {problems.length > 0 && name && (
        <Typography.Body variant="small" className="muted">
          {problems.join(". ")}
        </Typography.Body>
      )}
    </div>
  );
}
