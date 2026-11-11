// Public site settings. Everything here is visible to visitors by design.
// The Supabase key is a *publishable* key: the database only lets it insert into the
// evaluation-requests table (row-level security), never read it. Never put a secret or
// service_role key in this file.
window.ADAPTIVE_IDS_SITE = {
  supabaseUrl: "https://iemfjnspqlobfjvucdsi.supabase.co",
  supabasePublishableKey: "sb_publishable_XmC893WTfmjviOz7HNUGKA_MLBIdrKF",
  requestsTable: "adaptive_ids_evaluation_requests",
  // Optional links: leave empty to hide them.
  linkedinUrl: "",
  githubUrl: "https://github.com/MuhammadHaiderAbbas/Ml-Detection-Project",
  // Optional public contact address for the privacy notice; leave empty to use the form only.
  contactEmail: "",
};
