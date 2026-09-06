/** Create / register a brand profile. */

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, createProfile } from "../lib/api";
import type { ProfileCreatedResponse } from "../lib/types";
import { Banner, Button, Card } from "./ui";

const FIELD =
  "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100";
const LABEL = "block text-sm font-medium text-slate-700 dark:text-slate-300";

export function ProfileForm({
  onCreated,
}: {
  onCreated: (profile: ProfileCreatedResponse) => void;
}) {
  const [name, setName] = useState("Surfer SEO");
  const [domain, setDomain] = useState("surferseo.com");
  const [industry, setIndustry] = useState("SEO Software");
  const [description, setDescription] = useState("AI content optimization platform");
  const [competitors, setCompetitors] = useState("clearscope.io, frase.io");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const profile = await createProfile({
        name: name.trim(),
        domain: domain.trim(),
        industry: industry.trim() || null,
        description: description.trim() || null,
        competitors: competitors
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
      });
      onCreated(profile);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong creating the profile.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="1 · Create a profile" description="Register the brand you want to analyze.">
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="pf-name" className={LABEL}>
              Brand name <span className="text-rose-500">*</span>
            </label>
            <input
              id="pf-name"
              className={FIELD}
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="Surfer SEO"
            />
          </div>
          <div>
            <label htmlFor="pf-domain" className={LABEL}>
              Domain <span className="text-rose-500">*</span>
            </label>
            <input
              id="pf-domain"
              className={FIELD}
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              required
              placeholder="surferseo.com"
            />
          </div>
          <div>
            <label htmlFor="pf-industry" className={LABEL}>
              Industry
            </label>
            <input
              id="pf-industry"
              className={FIELD}
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="SEO Software"
            />
          </div>
          <div>
            <label htmlFor="pf-competitors" className={LABEL}>
              Competitors <span className="text-slate-400">(comma-separated)</span>
            </label>
            <input
              id="pf-competitors"
              className={FIELD}
              value={competitors}
              onChange={(e) => setCompetitors(e.target.value)}
              placeholder="clearscope.io, frase.io"
            />
          </div>
        </div>
        <div>
          <label htmlFor="pf-description" className={LABEL}>
            Description
          </label>
          <textarea
            id="pf-description"
            className={FIELD}
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What the brand does…"
          />
        </div>

        {error && (
          <Banner tone="error" title="Could not create profile">
            {error}
          </Banner>
        )}

        <div className="flex justify-end">
          <Button type="submit" busy={busy} disabled={!name.trim() || !domain.trim()}>
            {busy ? "Creating…" : "Create profile"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
