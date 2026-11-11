-- Applied to the Supabase project "MHaiderAbbas Portfolio" (eu-west-2) on 2026-11-11 as migration
-- adaptive_ids_evaluation_requests. Kept here so the table can be recreated in another project.
-- Anonymous visitors may INSERT only (no read, update or delete); rows are read in the Supabase dashboard.
create table public.adaptive_ids_evaluation_requests (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  name text not null check (char_length(btrim(name)) between 2 and 120),
  email text not null check (char_length(email) <= 254 and email ~* '^[^@\s]+@[^@\s]+\.[^@\s]{2,}$'),
  organisation text not null check (char_length(btrim(organisation)) between 2 and 160),
  role text check (role is null or char_length(role) <= 120),
  organisation_type text not null check (organisation_type in ('mssp', 'sme', 'enterprise', 'public_sector', 'education', 'other')),
  interest text not null check (interest in ('evaluation', 'feedback_call', 'partnership', 'other')),
  message text check (message is null or char_length(message) <= 2000),
  consent boolean not null check (consent),
  source text not null default 'website' check (char_length(source) <= 40)
);

alter table public.adaptive_ids_evaluation_requests enable row level security;
revoke all on table public.adaptive_ids_evaluation_requests from anon, authenticated;
grant insert (name, email, organisation, role, organisation_type, interest, message, consent, source)
  on table public.adaptive_ids_evaluation_requests to anon;
create policy "website visitors can submit requests" on public.adaptive_ids_evaluation_requests
  for insert to anon with check (consent and source = 'website');

-- One request per email per 10 minutes; at most 100 per hour overall.
create or replace function public.adaptive_ids_evaluation_requests_limit()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if exists (select 1 from public.adaptive_ids_evaluation_requests r
             where lower(r.email) = lower(new.email) and r.created_at > now() - interval '10 minutes') then
    raise exception 'too many requests from this email address; please try again later' using errcode = 'P0001';
  end if;
  if (select count(*) from public.adaptive_ids_evaluation_requests r where r.created_at > now() - interval '1 hour') >= 100 then
    raise exception 'the form is temporarily busy; please email instead' using errcode = 'P0001';
  end if;
  new.email := lower(btrim(new.email)); new.name := btrim(new.name); new.organisation := btrim(new.organisation);
  return new;
end; $$;
revoke all on function public.adaptive_ids_evaluation_requests_limit() from public, anon, authenticated;
create trigger adaptive_ids_evaluation_requests_limit before insert on public.adaptive_ids_evaluation_requests
  for each row execute function public.adaptive_ids_evaluation_requests_limit();
create index adaptive_ids_evaluation_requests_email_created_idx
  on public.adaptive_ids_evaluation_requests (lower(email), created_at desc);
