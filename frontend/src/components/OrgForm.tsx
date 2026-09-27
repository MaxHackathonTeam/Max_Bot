import { MapPin } from "lucide-react";
import { useState } from "react";
import type { Locality } from "../api/client";
import { ORG_KINDS, type Org, type OrgInput, type OrgKind } from "../api/organizer";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { Field, Input, Textarea } from "../ui/Field";
import { Sheet } from "../ui/Sheet";
import { FormErrors } from "./FormErrors";
import { LocalityPicker } from "./LocalityPicker";

const INN = /^(\d{10}|\d{12})$/;

/** Создание и правка организации. Реквизиты вводятся вручную — их сверяют при проверке. */
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
    initial?.locality_id ? { id: initial.locality_id, name: initial.locality_name ?? "" } : null,
  );
  const [picking, setPicking] = useState(false);

  const nameError = name && name.trim().length < 2 ? "Хотя бы 2 символа" : null;
  const innError = inn.trim() && !INN.test(inn.trim()) ? "10 или 12 цифр" : null;
  const siteError = website.trim() && !/^https:\/\/\S+$/.test(website.trim()) ? "Ссылка должна начинаться с https://" : null;
  const invalid = name.trim().length < 2 || Boolean(innError || siteError);

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
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalid) submit();
      }}
    >
      <Field label="Название" error={nameError}>
        {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} maxLength={255} autoComplete="organization" />}
      </Field>

      <fieldset className="filter-group">
        <legend className="field__label">Тип</legend>
        <div className="chips">
          {ORG_KINDS.map((k) => (
            <Chip key={k.value} pressed={kind === k.value} onClick={() => setKind(k.value)}>
              {k.label}
            </Chip>
          ))}
        </div>
      </fieldset>

      <Field label="ИНН" hint="Необязательно, но ускорит проверку" error={innError}>
        {(p) => (
          <Input
            {...p}
            inputMode="numeric"
            placeholder="10 или 12 цифр"
            value={inn}
            onChange={(e) => setInn(e.target.value.replace(/\D/g, "").slice(0, 12))}
          />
        )}
      </Field>

      <div className="field">
        <span className="field__label">Населённый пункт</span>
        <div>
          <Button variant="secondary" icon={<MapPin size={16} aria-hidden />} onClick={() => setPicking(true)}>
            {locality ? locality.name : "Выбрать"}
          </Button>
        </div>
      </div>

      <Field label="Адрес">
        {(p) => <Input {...p} value={address} onChange={(e) => setAddress(e.target.value)} maxLength={500} />}
      </Field>
      <Field label="Сайт или страница ВК" error={siteError}>
        {(p) => <Input {...p} type="url" placeholder="https://" value={website} onChange={(e) => setWebsite(e.target.value)} />}
      </Field>
      <div className="two-col">
        <Field label="Телефон организации">
          {(p) => <Input {...p} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={32} />}
        </Field>
        <Field label="E-mail организации">
          {(p) => <Input {...p} type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={255} />}
        </Field>
      </div>
      <Field label="Коротко об организации">
        {(p) => <Textarea {...p} rows={4} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />}
      </Field>

      <FormErrors error={error} />
      <Button type="submit" variant="primary" size="lg" block disabled={invalid} loading={busy}>
        {submitLabel}
      </Button>

      <Sheet open={picking} onClose={() => setPicking(false)} title="Населённый пункт">
        <LocalityPicker
          onPick={(l: Locality) => {
            setLocality({ id: l.id, name: l.name });
            setPicking(false);
          }}
        />
      </Sheet>
    </form>
  );
}
