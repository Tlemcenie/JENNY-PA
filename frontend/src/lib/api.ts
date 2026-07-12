const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data?: unknown
  ) {
    super(`${status} ${statusText}`);
    this.name = "ApiError";
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("jenny_token");
}

function setToken(token: string): void {
  localStorage.setItem("jenny_token", token);
}

function clearToken(): void {
  localStorage.removeItem("jenny_token");
}

async function request<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {}, signal } = options;
  const token = getToken();

  const config: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    signal,
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  const res = await fetch(`${API_BASE}${endpoint}`, config);

  if (!res.ok) {
    let data;
    try {
      data = await res.json();
    } catch {
      // ignore
    }
    throw new ApiError(res.status, res.statusText, data);
  }

  // 204 No Content (ex. DELETE) → pas de corps JSON à parser.
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

async function uploadFile<T>(endpoint: string, formData: FormData): Promise<T> {
  const token = getToken();

  const res = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  });

  if (!res.ok) {
    let data;
    try {
      data = await res.json();
    } catch {
      // ignore
    }
    throw new ApiError(res.status, res.statusText, data);
  }

  return res.json();
}

// ==================== AUTH ====================

interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role?: string;
  status?: string;
  business_id: string;
  business_name?: string;
  is_superuser?: boolean;
}

export async function login(email: string, password: string): Promise<{ token: string; user: User }> {
  const data = await request<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
  setToken(data.access_token);
  const user = await getMe();
  return { token: data.access_token, user };
}

export interface RegisterResult {
  status: "verification_required";
  email: string;
}

export async function register(
  fullName: string,
  email: string,
  password: string
): Promise<RegisterResult> {
  // Le backend renvoie 202 (vérification requise) — aucun token n'est émis
  // tant que l'email n'est pas confirmé via /verify-email.
  return request<RegisterResult>("/api/v1/auth/register", {
    method: "POST",
    body: { full_name: fullName, email, password },
  });
}

export async function verifyEmail(
  email: string,
  code: string
): Promise<{ token: string; user: User }> {
  const data = await request<LoginResponse>("/api/v1/auth/verify-email", {
    method: "POST",
    body: { email, code },
  });
  setToken(data.access_token);
  const user = await getMe();
  return { token: data.access_token, user };
}

export async function resendCode(email: string): Promise<void> {
  await request("/api/v1/auth/resend-code", {
    method: "POST",
    body: { email },
  });
}

export async function getMe(): Promise<User> {
  return request<User>("/api/v1/auth/me");
}

export interface UpdateMePayload {
  full_name?: string;
  current_password?: string;
  new_password?: string;
}

export async function updateMe(payload: UpdateMePayload): Promise<User> {
  return request<User>("/api/v1/auth/me", { method: "PATCH", body: payload });
}

export function logout(): void {
  clearToken();
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

// ==================== CONVERSATION / CHAT ====================

interface ConversationRequest {
  conversation_id: string;
  business_id: string;
  message: string;
  channel?: string;
  customer_id?: string;
  language?: string;
}

export interface ConversationResponse {
  response: string;
  intent: string;
  intent_confidence: number;
  detected_intents: Array<{ intent: string; confidence: number }>;
  is_multi_intent: boolean;
  needs_clarification: boolean;
  entities: Record<string, string>;
  agent_used: string;
  action_result: Record<string, unknown>;
  conversation_phase: string;
  requires_human: boolean;
  // Id du message Jenny persisté → cible d'un feedback 👍/👎.
  message_id: string | null;
}

export async function sendMessage(
  conversationId: string,
  businessId: string,
  message: string,
  signal?: AbortSignal
): Promise<ConversationResponse> {
  return request<ConversationResponse>("/api/v1/conversation/chat", {
    method: "POST",
    body: {
      conversation_id: conversationId,
      business_id: businessId,
      message,
      channel: "api",
      language: "fr",
    } satisfies ConversationRequest,
    signal,
  });
}

export async function getConversationStatus(conversationId: string) {
  return request(`/api/v1/conversation/status/${conversationId}`);
}

// ==================== FEEDBACK RÉPONSES (👍/👎) ====================

export type FeedbackRating = 1 | -1;

export interface FeedbackState {
  message_id: string;
  rating: number | null; // null = pas encore évalué
  comment: string | null;
}

export interface FeedbackMetrics {
  total_rated: number;
  positive: number;
  negative: number;
  satisfaction_pct: number; // part de 👍 parmi les avis (0–100)
  coverage_rated: number;
  responses_total: number; // nombre total de réponses de Jenny
  last_7_days: { positive: number; negative: number };
  recent_comments: FeedbackContext[];
  recent_positive: FeedbackContext[];
}

export interface FeedbackContext {
  comment: string | null;
  question: string | null;
  answer: string | null;
  created_at: string;
}

export async function submitFeedback(
  messageId: string,
  rating: FeedbackRating,
  comment?: string
): Promise<FeedbackState> {
  return request<FeedbackState>("/api/v1/feedback", {
    method: "POST",
    body: { message_id: messageId, rating, comment: comment ?? null },
  });
}

export async function getFeedbackMetrics(): Promise<FeedbackMetrics> {
  return request<FeedbackMetrics>("/api/v1/feedback/metrics");
}

// ==================== MESSAGES ====================

export interface Message {
  id: string;
  channel: string;
  direction: string;
  sender_name: string;
  content: string;
  status: string;
  priority: number;
  category: string;
  conversation_id: string;
  created_at: string;
}

interface MessageListResponse {
  messages: Message[];
  next_cursor: string | null;
  total?: number;
}

export async function listMessages(
  businessId: string,
  params: {
    channel?: string;
    status?: string;
    limit?: number;
    cursor?: string;
    from_date?: string;
    to_date?: string;
  } = {}
): Promise<MessageListResponse> {
  const searchParams = new URLSearchParams({ business_id: businessId });
  Object.entries(params).forEach(([key, value]) => {
    if (value) searchParams.set(key, String(value));
  });
  return request<MessageListResponse>(`/api/v1/messages/?${searchParams}`);
}

export async function getMessage(messageId: string, businessId: string): Promise<Message> {
  return request<Message>(`/api/v1/messages/${messageId}?business_id=${businessId}`);
}

// ==================== KNOWLEDGE BASE ====================

export interface KnowledgeEntry {
  id: string;
  business_id: string;
  title: string;
  content_preview?: string;
  category: string;
  source: string;
  chunks_count?: number;
  created_at: string;
}

interface KnowledgeStats {
  business_id?: string;
  total_entries: number;
  total_chunks?: number;
  by_category: Record<string, number>;
  by_source?: Record<string, number>;
}

export async function listKnowledgeEntries(businessId: string): Promise<KnowledgeEntry[]> {
  return request<KnowledgeEntry[]>(`/api/v1/knowledge/entries/${businessId}`);
}

export async function addKnowledgeText(
  businessId: string,
  title: string,
  content: string,
  category: string
): Promise<KnowledgeEntry> {
  return request<KnowledgeEntry>("/api/v1/knowledge/text", {
    method: "POST",
    body: { business_id: businessId, title, content, category },
  });
}

export async function uploadKnowledgePdf(
  businessId: string,
  file: File,
  title: string,
  category: string
): Promise<KnowledgeEntry> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("business_id", businessId);
  formData.append("title", title);
  formData.append("category", category);
  return uploadFile<KnowledgeEntry>("/api/v1/knowledge/pdf", formData);
}

export async function deleteKnowledgeEntry(businessId: string, entryId: string): Promise<void> {
  await request(`/api/v1/knowledge/entries/${businessId}/${entryId}`, { method: "DELETE" });
}

export async function getKnowledgeStats(businessId: string): Promise<KnowledgeStats> {
  return request<KnowledgeStats>(`/api/v1/knowledge/stats/${businessId}`);
}

// ── Édition d'une entrée (#12) ──
export async function updateKnowledgeEntry(
  businessId: string,
  entryId: string,
  payload: { title: string; content: string; category: string }
): Promise<KnowledgeEntry> {
  return request<KnowledgeEntry>(
    `/api/v1/knowledge/entries/${businessId}/${entryId}`,
    { method: "PUT", body: payload }
  );
}

// ── Recherche sémantique dans la base (#12) ──
export interface KnowledgeSearchHit {
  content: string;
  score: number;
  title: string | null;
  category: string | null;
}

export async function searchKnowledge(
  businessId: string,
  q: string,
  topK = 5
): Promise<KnowledgeSearchHit[]> {
  const qs = new URLSearchParams({ q, top_k: String(topK) }).toString();
  return request<KnowledgeSearchHit[]>(`/api/v1/knowledge/search/${businessId}?${qs}`);
}

// ── Import multi-fichiers (#13) ──
export interface MultiImportResult {
  imported: KnowledgeEntry[];
  errors: { file: string; error: string }[];
}

export async function uploadKnowledgeFiles(
  businessId: string,
  files: File[],
  category: string
): Promise<MultiImportResult> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  formData.append("business_id", businessId);
  formData.append("category", category);
  return uploadFile<MultiImportResult>("/api/v1/knowledge/files", formData);
}

// ==================== BUSINESS (CONFIGURATION) ====================

export type BusinessHours = Record<string, [string, string] | null>;

export interface BusinessConfig {
  id: string;
  name: string;
  slug: string;
  email: string | null;
  phone: string | null;
  description: string | null;
  timezone: string;
  is_active: boolean;
  business_hours: BusinessHours | null;
  auto_reply_message: string | null;
  sla_minutes: number;
  sla_rules: SlaRules | null;
  persona: JennyPersona | null;
  // Acompte anti-no-show (#brain) : demander un acompte réduit les RDV manqués.
  deposit_enabled: boolean;
  deposit_percent: number; // % du prix de la prestation demandé en acompte (0–100)
  deposit_min_cents: number; // acompte forfaitaire (en centimes) quand le prix est inconnu
  // Rappels & fidélité (#salon) : délais de relance + seuil de récompense.
  reminder_lead_minutes: number; // rappel imminent : minutes avant le RDV
  day_reminder_lead_hours: number; // rappel la veille : heures avant le RDV
  loyalty_threshold: number; // récompense après N rendez-vous (0 = désactivé)
  created_at: string;
}

// « Cerveau de Jenny » — personnalité configurable (#brain).
export interface JennyPersona {
  tone?: string; // pro | cool | vendeur | chaleureux
  sliders?: Record<string, number>; // formel↔décontracté, concis↔détaillé, …
  tutoiement?: boolean;
  vocab?: string[];
  rules?: { label: string; on: boolean }[];
}

// SLA fins par priorité/canal (#7) : minutes avant « en retard ».
export interface SlaRules {
  priority?: Partial<Record<PriorityLevel, number>>;
  channel?: Record<string, number>;
}

export interface BusinessUpdatePayload {
  name?: string;
  email?: string | null;
  phone?: string | null;
  description?: string | null;
  timezone?: string;
  business_hours?: BusinessHours | null;
  auto_reply_message?: string | null;
  sla_minutes?: number;
  sla_rules?: SlaRules | null;
  persona?: JennyPersona | null;
  deposit_enabled?: boolean;
  deposit_percent?: number;
  deposit_min_cents?: number;
  reminder_lead_minutes?: number;
  day_reminder_lead_hours?: number;
  loyalty_threshold?: number;
}

export async function getBusiness(): Promise<BusinessConfig> {
  return request<BusinessConfig>("/api/v1/business/me");
}

export interface TeamMember {
  user_id: string;
  email: string;
  full_name: string | null;
  role: string;
}

export async function listMembers(): Promise<TeamMember[]> {
  return request<TeamMember[]>("/api/v1/business/members");
}

export async function addMember(payload: {
  email: string;
  full_name?: string;
  password: string;
  role?: string;
}): Promise<TeamMember> {
  return request<TeamMember>("/api/v1/business/members", {
    method: "POST",
    body: payload,
  });
}

export async function assignConversation(
  conversationId: string,
  assignee: string | null
): Promise<{ assigned_to: string | null }> {
  return request<{ assigned_to: string | null }>(
    `/api/v1/conversations/${conversationId}/assign`,
    { method: "POST", body: { assignee } }
  );
}

export async function updateBusiness(payload: BusinessUpdatePayload): Promise<BusinessConfig> {
  return request<BusinessConfig>("/api/v1/business/me", { method: "PATCH", body: payload });
}

// ==================== INSIGHTS (DASHBOARD) ====================

export interface ChannelStat {
  channel: string;
  count: number;
}

export interface IntentStat {
  intent: string;
  count: number;
}

export interface DailyStat {
  date: string;
  count: number;
}

export interface AgentStat {
  agent: string;
  count: number;
}

export interface Insights {
  business_id: string | null;
  conversations_total: number;
  conversations_open: number;
  conversations_escalated: number;
  messages_total: number;
  messages_inbound: number;
  messages_outbound: number;
  customers_total: number;
  orders_total: number;
  revenue_minor: number;
  currency: string;
  knowledge_entries: number;
  escalation_rate: number;
  avg_messages_per_conversation: number;
  avg_first_response_minutes: number | null;
  by_channel: ChannelStat[];
  by_agent: AgentStat[];
  top_intents: IntentStat[];
  messages_last_7_days: DailyStat[];
}

export async function getInsights(days?: number): Promise<Insights> {
  const qs = days ? `?days=${days}` : "";
  return request<Insights>(`/api/v1/insights${qs}`);
}

// ==================== CANAUX ====================

export interface ChannelStatus {
  channel: string;
  label: string;
  connected: boolean;
  builtin: boolean;
  configurable?: boolean;
  account: string | null;
  outbound_ready?: boolean;
  last_error?: string | null;
}

export interface ChannelFieldSpec {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  placeholder: string;
}

export interface ChannelWebhookInfo {
  channel: string;
  url: string;
  verify_token: string | null;
  note: string | null;
}

export interface ChannelTestResult {
  ok: boolean;
  detail: string;
}

export async function listChannels(): Promise<ChannelStatus[]> {
  return request<ChannelStatus[]>("/api/v1/channels");
}

export async function getChannelFields(channel: string): Promise<ChannelFieldSpec[]> {
  const res = await request<{ channel: string; fields: ChannelFieldSpec[] }>(
    `/api/v1/channels/${channel}/fields`
  );
  return res.fields;
}

export async function getChannelWebhookInfo(channel: string): Promise<ChannelWebhookInfo> {
  return request<ChannelWebhookInfo>(`/api/v1/channels/${channel}/webhook-info`);
}

export async function connectChannel(
  channel: string,
  payload: { display_name?: string; credentials: Record<string, string> }
): Promise<ChannelStatus> {
  return request<ChannelStatus>(`/api/v1/channels/${channel}/connect`, {
    method: "POST",
    body: payload,
  });
}

export async function disconnectChannel(channel: string): Promise<void> {
  await request<void>(`/api/v1/channels/${channel}`, { method: "DELETE" });
}

export async function testChannel(channel: string): Promise<ChannelTestResult> {
  return request<ChannelTestResult>(`/api/v1/channels/${channel}/test`, { method: "POST" });
}

// ==================== IMPORT CLIENTS ====================

export async function importCustomersCsv(
  file: File
): Promise<{ created: number; skipped: number }> {
  const formData = new FormData();
  formData.append("file", file);
  return uploadFile<{ created: number; skipped: number }>(
    "/api/v1/customers/import",
    formData
  );
}

// ==================== CONVERSATIONS (HISTORIQUE) ====================

export interface ConversationSummary {
  id: string;
  channel: string;
  status: string;
  priority_level: string;
  current_intent: string | null;
  message_count: number;
  is_escalated: boolean;
  last_message_at: string | null;
  customer_id: string | null;
  customer_name: string | null;
  last_message_preview: string | null;
  awaiting_reply: boolean;
  overdue: boolean;
  waiting_minutes: number | null;
  sentiment: string | null;
  tags: string[];
  created_at: string;
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversationMessageItem {
  id: string;
  direction: string;
  sender_name: string | null;
  content: string;
  channel: string;
  status: string;
  attachment_count?: number;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  channel: string;
  status: string;
  priority_level: string;
  current_intent: string | null;
  message_count: number;
  is_escalated: boolean;
  last_message_at: string | null;
  summary: string | null;
  customer_id: string | null;
  customer_name: string | null;
  assigned_to: string | null;
  sentiment: string | null;
  snoozed_until: string | null;
  tags: string[];
  created_at: string;
  messages: ConversationMessageItem[];
}

export interface ReplyResult {
  message: ConversationMessageItem;
  delivered: boolean;
  assigned_to: string | null;
}

export async function replyToConversation(
  conversationId: string,
  text: string
): Promise<ReplyResult> {
  return request<ReplyResult>(`/api/v1/conversations/${conversationId}/reply`, {
    method: "POST",
    body: { text },
  });
}

export async function resumeConversation(
  conversationId: string
): Promise<{ assigned_to: string | null }> {
  return request<{ assigned_to: string | null }>(
    `/api/v1/conversations/${conversationId}/resume`,
    { method: "POST" }
  );
}

export async function suggestReply(
  conversationId: string
): Promise<{ suggestion: string; variants: string[] }> {
  return request<{ suggestion: string; variants: string[] }>(
    `/api/v1/conversations/${conversationId}/suggest`,
    { method: "POST" }
  );
}

export async function snoozeConversation(
  conversationId: string,
  minutes: number | null
): Promise<{ snoozed_until: string | null }> {
  return request<{ snoozed_until: string | null }>(
    `/api/v1/conversations/${conversationId}/snooze`,
    { method: "POST", body: { minutes } }
  );
}

export async function summarizeConversation(
  conversationId: string
): Promise<{ summary: string }> {
  return request<{ summary: string }>(
    `/api/v1/conversations/${conversationId}/summarize`,
    { method: "POST" }
  );
}

export async function updateConversationTags(
  conversationId: string,
  tags: string[]
): Promise<{ tags: string[] }> {
  return request<{ tags: string[] }>(
    `/api/v1/conversations/${conversationId}/tags`,
    { method: "PATCH", body: { tags } }
  );
}

export type ConversationStatus = "open" | "closed" | "archived";

export async function updateConversationStatus(
  conversationId: string,
  status: ConversationStatus
): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/v1/conversations/${conversationId}/status`,
    { method: "PATCH", body: { status } }
  );
}

export type ConversationSort = "recent" | "oldest" | "priority";
export type PriorityLevel = "low" | "medium" | "high" | "critical";

export async function listConversations(
  params: {
    status?: string;
    channel?: string;
    search?: string;
    assigned_to?: string;
    tag?: string;
    priority?: string;
    sort_by?: ConversationSort;
    limit?: number;
    offset?: number;
  } = {}
): Promise<ConversationListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const qs = searchParams.toString();
  return request<ConversationListResponse>(`/api/v1/conversations${qs ? `?${qs}` : ""}`);
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/v1/conversations/${conversationId}`);
}

export async function getConversationStats(): Promise<{ awaiting: number }> {
  return request<{ awaiting: number }>("/api/v1/conversations/stats");
}

// ── Priorité (#4) ──
export async function updateConversationPriority(
  conversationId: string,
  priority_level: PriorityLevel
): Promise<{ priority_level: string }> {
  return request<{ priority_level: string }>(
    `/api/v1/conversations/${conversationId}/priority`,
    { method: "PATCH", body: { priority_level } }
  );
}

// ── Actions groupées (#1) ──
export type BulkAction = "status" | "assign" | "priority" | "tag_add" | "tag_remove";

export async function bulkConversationAction(
  ids: string[],
  action: BulkAction,
  value: string | null
): Promise<{ updated: number }> {
  return request<{ updated: number }>("/api/v1/conversations/bulk", {
    method: "POST",
    body: { ids, action, value },
  });
}

// ── Fusion (#10) ──
export async function mergeConversations(
  targetId: string,
  sourceId: string
): Promise<{ target_id: string; merged_messages: number; message_count: number }> {
  return request(`/api/v1/conversations/${targetId}/merge`, {
    method: "POST",
    body: { source_id: sourceId },
  });
}

// ── Recherche plein-texte des messages (#8) ──
export interface MessageSearchHit {
  conversation_id: string;
  message_id: string;
  direction: string;
  channel: string;
  snippet: string;
  customer_name: string | null;
  created_at: string;
}

export interface MessageSearchResponse {
  query: string;
  hits: MessageSearchHit[];
  total: number;
}

export async function searchMessages(
  q: string,
  limit = 30
): Promise<MessageSearchResponse> {
  const qs = new URLSearchParams({ q, limit: String(limit) }).toString();
  return request<MessageSearchResponse>(`/api/v1/conversations/search/messages?${qs}`);
}

// ==================== FICHE CLIENT 360° ====================

export interface CustomerConversationItem {
  id: string;
  channel: string;
  status: string;
  message_count: number;
  last_message_at: string | null;
  created_at: string;
}

export interface CustomerOrderItem {
  id: string;
  reference: string | null;
  status: string;
  currency: string;
  total_amount_minor: number | null;
  created_at: string;
}

export interface CustomerTransactionItem {
  id: string;
  label: string;
  amount_minor: number;
  currency: string;
  status: string;
  occurred_at: string;
}

export interface CustomerTicketItem {
  id: string;
  reference: string | null;
  subject: string | null;
  status: string;
  priority: string;
  created_at: string;
}

export interface CustomerStats {
  conversations: number;
  messages: number;
  orders: number;
  open_tickets: number;
  total_spent_minor: number;
  currency: string;
}

export interface Customer360 {
  id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  instagram_handle: string | null;
  tags: string[];
  notes: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  created_at: string;
  stats: CustomerStats;
  conversations: CustomerConversationItem[];
  orders: CustomerOrderItem[];
  transactions: CustomerTransactionItem[];
  tickets: CustomerTicketItem[];
}

export interface CustomerUpdatePayload {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  notes?: string | null;
  tags?: string[];
}

export interface CustomerUpdateResult {
  id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
  tags: string[];
}

export interface CustomerListItem {
  id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  instagram_handle: string | null;
  tags: string[];
  conversation_count: number;
  last_seen_at: string | null;
  created_at: string;
}

export interface CustomerListResponse {
  customers: CustomerListItem[];
  total: number;
  limit: number;
  offset: number;
}

export async function listCustomers(
  params: { search?: string; limit?: number; offset?: number } = {}
): Promise<CustomerListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const qs = searchParams.toString();
  return request<CustomerListResponse>(`/api/v1/customers${qs ? `?${qs}` : ""}`);
}

export async function getCustomer360(customerId: string): Promise<Customer360> {
  return request<Customer360>(`/api/v1/customers/${customerId}`);
}

export async function updateCustomer(
  customerId: string,
  payload: CustomerUpdatePayload
): Promise<CustomerUpdateResult> {
  return request<CustomerUpdateResult>(`/api/v1/customers/${customerId}`, {
    method: "PATCH",
    body: payload,
  });
}

// ==================== RÉPONSES ENREGISTRÉES ====================

export interface CannedResponse {
  id: string;
  shortcut: string | null;
  title: string;
  content: string;
  created_at: string;
}

export interface CannedResponsePayload {
  title: string;
  content: string;
  shortcut?: string | null;
}

export async function listCannedResponses(): Promise<CannedResponse[]> {
  return request<CannedResponse[]>("/api/v1/canned-responses");
}

export async function createCannedResponse(
  payload: CannedResponsePayload
): Promise<CannedResponse> {
  return request<CannedResponse>("/api/v1/canned-responses", {
    method: "POST",
    body: payload,
  });
}

export async function updateCannedResponse(
  id: string,
  payload: Partial<CannedResponsePayload>
): Promise<CannedResponse> {
  return request<CannedResponse>(`/api/v1/canned-responses/${id}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function deleteCannedResponse(id: string): Promise<void> {
  await request(`/api/v1/canned-responses/${id}`, { method: "DELETE" });
}

// ==================== TEMPS RÉEL (SSE) ====================

export interface RealtimeEvent {
  event: string;
  business_id: string;
  conversation_id: string | null;
  kind: "inbound" | "outbound" | "status" | "update" | "processing" | string;
  channel?: string | null;
  // Présents pour les événements `notification.new` (#14/#15).
  recipient?: string | null;
  title?: string;
  notification_id?: string | null;
}

/**
 * S'abonne au flux temps réel des conversations via SSE.
 *
 * On utilise `fetch` + ReadableStream (et non `EventSource` natif) car le flux
 * est protégé par un header `Authorization: Bearer` qu'`EventSource` ne sait pas
 * envoyer. Reconnexion automatique avec back-off exponentiel.
 *
 * Renvoie une fonction de désabonnement (à appeler au démontage).
 */
export function subscribeToConversationEvents(
  onEvent: (event: RealtimeEvent) => void,
  onConnectionChange?: (connected: boolean) => void
): () => void {
  const controller = new AbortController();
  let closed = false;

  async function loop() {
    let backoff = 1000;
    while (!closed) {
      try {
        const token = getToken();
        const res = await fetch(`${API_BASE}/api/v1/realtime/stream`, {
          headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`);

        onConnectionChange?.(true);
        backoff = 1000;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!closed) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // Les événements SSE sont séparés par une ligne vide (\n\n).
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
            if (!dataLine) continue; // commentaire (heartbeat) ou ligne d'event
            const payload = dataLine.slice(5).trim();
            if (!payload) continue;
            try {
              onEvent(JSON.parse(payload) as RealtimeEvent);
            } catch {
              // trame partielle / non-JSON → ignorer
            }
          }
        }
      } catch {
        if (closed || controller.signal.aborted) break;
        onConnectionChange?.(false);
      }
      if (closed) break;
      await new Promise((r) => setTimeout(r, backoff));
      backoff = Math.min(backoff * 2, 15000);
    }
  }

  void loop();

  return () => {
    closed = true;
    onConnectionChange?.(false);
    controller.abort();
  };
}

// ==================== NOTIFICATIONS (#14/#15) ====================

export interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  conversation_id: string | null;
  read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  notifications: NotificationItem[];
  unread: number;
  total: number;
}

export async function listNotifications(
  onlyUnread = false,
  limit = 30
): Promise<NotificationListResponse> {
  const qs = new URLSearchParams({
    only_unread: String(onlyUnread),
    limit: String(limit),
  }).toString();
  return request<NotificationListResponse>(`/api/v1/notifications?${qs}`);
}

export async function getUnreadNotificationCount(): Promise<{ unread: number }> {
  return request<{ unread: number }>("/api/v1/notifications/unread-count");
}

export async function markNotificationRead(id: string): Promise<{ unread: number }> {
  return request<{ unread: number }>(`/api/v1/notifications/${id}/read`, {
    method: "POST",
  });
}

export async function markAllNotificationsRead(): Promise<{ unread: number }> {
  return request<{ unread: number }>("/api/v1/notifications/read-all", {
    method: "POST",
  });
}

// ==================== JOURNAL D'AUDIT (#16) ====================

export interface AuditItem {
  id: string;
  actor: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditListResponse {
  items: AuditItem[];
  total: number;
}

export async function listAudit(
  params: { action?: string; actor?: string; entity_id?: string; limit?: number; offset?: number } = {}
): Promise<AuditListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const qs = searchParams.toString();
  return request<AuditListResponse>(`/api/v1/audit${qs ? `?${qs}` : ""}`);
}

// ==================== CLÉS API (#17) ====================

export interface ApiKeyInfo {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKeyInfo {
  secret: string;
}

export async function listApiKeys(): Promise<ApiKeyInfo[]> {
  return request<ApiKeyInfo[]>("/api/v1/api-keys");
}

export async function createApiKey(payload: {
  name: string;
  scopes?: string[];
  expires_in_days?: number | null;
}): Promise<ApiKeyCreated> {
  return request<ApiKeyCreated>("/api/v1/api-keys", { method: "POST", body: payload });
}

export async function revokeApiKey(id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/v1/api-keys/${id}`, { method: "DELETE" });
}

// ==================== CALENDRIER / RENDEZ-VOUS ====================

export interface Appointment {
  id: string;
  title: string;
  description: string | null;
  location: string | null;
  channel: string | null;
  start_at: string;
  end_at: string;
  status: string;
  staff_notes: string | null;
  customer_id: string | null;
  customer_name: string | null;
  conversation_id: string | null;
  created_by: string | null;
}

export interface AppointmentCreatePayload {
  title: string;
  start_at: string;
  end_at: string;
  description?: string | null;
  location?: string | null;
  channel?: string | null;
  customer_id?: string | null;
  conversation_id?: string | null;
}

export async function listAppointments(params: {
  start?: string;
  end?: string;
  limit?: number;
} = {}): Promise<{ appointments: Appointment[]; total: number }> {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  });
  const s = qs.toString();
  return request(`/api/v1/appointments${s ? `?${s}` : ""}`);
}

export async function createAppointment(payload: AppointmentCreatePayload): Promise<Appointment> {
  return request<Appointment>("/api/v1/appointments", { method: "POST", body: payload });
}

export async function updateAppointment(
  id: string,
  payload: Partial<
    Pick<Appointment, "title" | "description" | "location" | "status" | "staff_notes" | "start_at" | "end_at">
  >
): Promise<Appointment> {
  return request<Appointment>(`/api/v1/appointments/${id}`, { method: "PATCH", body: payload });
}

export async function deleteAppointment(id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/v1/appointments/${id}`, { method: "DELETE" });
}

// Avis client laissé par l'équipe après un rendez-vous passé (#salon).
export async function createReview(body: {
  rating: number;
  comment?: string;
  customer_id?: string;
  appointment_id?: string;
}): Promise<{ id: string; rating: number }> {
  return request("/api/v1/salon/reviews", { method: "POST", body });
}

// ==================== ADMIN (super-admin plateforme) ====================

export interface AdminOverview {
  businesses: number;
  users: number;
  conversations: number;
  messages: number;
  customers: number;
}

export interface AdminBusiness {
  id: string;
  name: string;
  slug: string;
  email: string | null;
  is_active: boolean;
  members: number;
  conversations: number;
  created_at: string;
}

export interface AdminUserItem {
  id: string;
  email: string;
  full_name: string | null;
  email_verified: boolean;
  is_superuser: boolean;
  businesses: number;
  created_at: string;
}

export async function getAdminOverview(): Promise<AdminOverview> {
  return request<AdminOverview>("/api/v1/admin/overview");
}

export async function listAdminBusinesses(): Promise<AdminBusiness[]> {
  return request<AdminBusiness[]>("/api/v1/admin/businesses");
}

export async function listAdminUsers(): Promise<AdminUserItem[]> {
  return request<AdminUserItem[]>("/api/v1/admin/users");
}

export async function setBusinessActive(id: string, isActive: boolean): Promise<AdminBusiness> {
  return request<AdminBusiness>(`/api/v1/admin/businesses/${id}/active`, {
    method: "PATCH",
    body: { is_active: isActive },
  });
}

export async function setUserSuperuser(id: string, isSuperuser: boolean): Promise<AdminUserItem> {
  return request<AdminUserItem>(`/api/v1/admin/users/${id}/superuser`, {
    method: "PATCH",
    body: { is_superuser: isSuperuser },
  });
}

// ── Journal d'audit GLOBAL (toutes entreprises) ──
// Même forme que `AuditItem`, enrichie de l'entreprise rattachée à chaque ligne.
export interface AdminAuditItem {
  id: string;
  actor: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  meta: Record<string, unknown> | null;
  created_at: string;
  business_id: string;
  business_name: string | null;
}

export interface AdminAuditListResponse {
  items: AdminAuditItem[];
  total: number;
}

export async function getAdminAudit(
  params: { limit?: number; offset?: number; q?: string } = {}
): Promise<AdminAuditListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const qs = searchParams.toString();
  return request<AdminAuditListResponse>(`/api/v1/admin/audit${qs ? `?${qs}` : ""}`);
}

// ==================== EXPORT CSV ====================

async function downloadExport(endpoint: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function exportConversationsCsv(): Promise<void> {
  return downloadExport("/api/v1/conversations/export.csv", "conversations.csv");
}

export function exportCustomersCsv(): Promise<void> {
  return downloadExport("/api/v1/customers/export.csv", "clients.csv");
}

export function exportAppointmentsIcs(): Promise<void> {
  return downloadExport("/api/v1/appointments/export.ics", "jenny-agenda.ics");
}

// ==================== RGPD (CLIENT) ====================

// Export RGPD d'un client : télécharge le JSON renvoyé par le backend
// (Content-Disposition: attachment), via le même flux blob authentifié.
export function exportCustomerData(customerId: string): Promise<void> {
  return downloadExport(`/api/v1/customers/${customerId}/export`, `client-${customerId}.json`);
}

// Anonymisation RGPD d'un client. IRRÉVERSIBLE : confirmer avant d'appeler.
export async function anonymizeCustomer(
  customerId: string
): Promise<{ anonymized?: boolean; already_anonymized?: boolean }> {
  return request(`/api/v1/customers/${customerId}/anonymize`, { method: "POST" });
}

// ==================== RECHERCHE GLOBALE (⌘K) ====================

export interface GlobalSearchConversation {
  id: string;
  customer_name: string | null;
  channel: string;
  preview: string | null;
}

export interface GlobalSearchCustomer {
  id: string;
  full_name: string | null;
  email: string | null;
}

export interface GlobalSearchAppointment {
  id: string;
  title: string;
  start_at: string;
}

export interface GlobalSearchResponse {
  query: string;
  conversations: GlobalSearchConversation[];
  customers: GlobalSearchCustomer[];
  appointments: GlobalSearchAppointment[];
}

export async function globalSearch(q: string, limit = 5): Promise<GlobalSearchResponse> {
  const qs = new URLSearchParams({ q, limit: String(limit) });
  return request<GlobalSearchResponse>(`/api/v1/search?${qs.toString()}`);
}

// ==================== MOT DE PASSE OUBLIÉ ====================

export async function forgotPassword(email: string): Promise<{ status: string; debug_code?: string }> {
  return request("/api/v1/auth/forgot-password", { method: "POST", body: { email } });
}

export async function resetPassword(
  email: string,
  code: string,
  newPassword: string
): Promise<{ status: string }> {
  return request("/api/v1/auth/reset-password", {
    method: "POST",
    body: { email, code, new_password: newPassword },
  });
}

// ==================== RÉSERVATION PUBLIQUE (/book/[slug]) ====================

export interface BookingBusinessInfo {
  name: string;
  slug: string;
  description: string | null;
  timezone: string;
  business_hours: Record<string, [string, string] | null> | null;
}

export interface BookingSlot {
  start_at: string;
  end_at: string;
  label: string;
}

export interface BookingSlotsResponse {
  date: string;
  timezone: string;
  duration_minutes: number;
  slots: BookingSlot[];
}

export interface BookingRequestPayload {
  full_name: string;
  email: string;
  phone?: string | null;
  start_at: string;
  duration?: number;
  notes?: string | null;
}

export interface BookingConfirmation {
  id: string;
  status: string;
  business_name: string;
  start_at: string;
  end_at: string;
  message: string;
}

export async function getBookingInfo(slug: string): Promise<BookingBusinessInfo> {
  return request<BookingBusinessInfo>(`/api/v1/public/booking/${encodeURIComponent(slug)}`);
}

export async function getBookingSlots(
  slug: string,
  dateIso: string,
  duration = 30
): Promise<BookingSlotsResponse> {
  const qs = new URLSearchParams({ date: dateIso, duration: String(duration) });
  return request<BookingSlotsResponse>(
    `/api/v1/public/booking/${encodeURIComponent(slug)}/slots?${qs.toString()}`
  );
}

export async function createBooking(
  slug: string,
  payload: BookingRequestPayload
): Promise<BookingConfirmation> {
  return request<BookingConfirmation>(
    `/api/v1/public/booking/${encodeURIComponent(slug)}/book`,
    { method: "POST", body: payload }
  );
}

// ==================== APPRENTISSAGE / LACUNES ====================

export interface KnowledgeGap {
  id: string;
  question: string;
  channel: string | null;
  intent: string | null;
  status: string;
  occurrences: number;
  answer: string | null;
  saved_to_kb: boolean;
  conversation_id: string | null;
  created_at: string;
  last_seen_at: string | null;
}

export interface GapStats {
  open: number;
  answered: number;
  dismissed: number;
  saved_to_kb: number;
}

export interface GapRecap {
  total_open: number;
  questions: string[];
  recap_text: string;
}

export async function listKnowledgeGaps(
  status: "open" | "answered" | "dismissed" | "all" = "open"
): Promise<{ gaps: KnowledgeGap[]; total: number }> {
  return request(`/api/v1/knowledge-gaps?status=${status}`);
}

export async function knowledgeGapStats(): Promise<GapStats> {
  return request<GapStats>("/api/v1/knowledge-gaps/stats");
}

export async function knowledgeGapRecap(): Promise<GapRecap> {
  return request<GapRecap>("/api/v1/knowledge-gaps/recap");
}

export async function answerKnowledgeGap(
  id: string,
  answer: string,
  saveToKb = true,
  category = "faq"
): Promise<{ gap: KnowledgeGap; saved_to_kb: boolean; knowledge_entry_id: string | null }> {
  return request(`/api/v1/knowledge-gaps/${id}/answer`, {
    method: "POST",
    body: { answer, save_to_kb: saveToKb, category },
  });
}

export async function dismissKnowledgeGap(id: string): Promise<KnowledgeGap> {
  return request<KnowledgeGap>(`/api/v1/knowledge-gaps/${id}/dismiss`, { method: "POST" });
}

// ==================== CO-PILOTE AGENT ====================

export interface CopilotSuggestion {
  suggestion: string;
  knowledge_gap: boolean;
  requires_human: boolean;
  detected_language: string | null;
}

export async function copilotSuggest(payload: {
  message: string;
  customer_id?: string | null;
  conversation_id?: string | null;
}): Promise<CopilotSuggestion> {
  return request<CopilotSuggestion>("/api/v1/copilot/suggest", { method: "POST", body: payload });
}

// ==================== EFFICACITÉ DE JENNY ====================

export interface JennyEvalSummary {
  score_pct: number;
  scenarios: number;
  turns: number;
  checks_passed: number;
  checks_total: number;
  by_criterion: Record<string, { pass: number; total: number; pct: number }>;
}

export interface SatisfactionBreakdown {
  total_rated: number;
  positive: number;
  negative: number;
  satisfaction_pct: number;
}

export interface JennyMetrics {
  conversations: number;
  messages: number;
  customers: number;
  learned_answers: number;
  gaps: GapStats;
  top_open_questions: string[];
  last_eval: JennyEvalSummary | null;
  satisfaction: SatisfactionBreakdown;
}

export async function getJennyMetrics(): Promise<JennyMetrics> {
  return request<JennyMetrics>("/api/v1/jenny/metrics");
}

// ==================== STATISTIQUES SALON ====================

export interface SalonStats {
  range_days: number;
  appointments_total: number;
  upcoming: number;
  completed: number;
  cancelled: number;
  cancellation_rate_pct: number;
  fill_rate_pct: number;
  top_prestations: { name: string; count: number }[];
  peak_hours: { hour: number; count: number }[];
  busiest_day: string | null;
  clients_total: number;
  loyal_clients: number;
  new_clients: number;
  revenue_upcoming_eur: number;
  deposits: { enabled: boolean; pending: number; paid: number; collected_eur: number };
  waitlist: { waiting: number; notified: number };
  // Satisfaction & absences (#salon).
  average_rating: number | null; // note moyenne /5 (null tant qu'aucun avis)
  reviews_count: number; // nombre d'avis pris en compte
  no_show: number; // rendez-vous où le client ne s'est pas présenté
}

export async function getSalonStats(rangeDays = 30): Promise<SalonStats> {
  return request<SalonStats>(`/api/v1/salon/stats?range_days=${rangeDays}`);
}

// ==================== FERMETURES EXCEPTIONNELLES (congés / jours fériés) ====================

export interface Closure {
  id: string;
  start_date: string;
  end_date: string;
  reason: string | null;
}

export async function listClosures(): Promise<Closure[]> {
  return request<Closure[]>("/api/v1/salon/closures");
}

export async function createClosure(body: {
  start_date: string;
  end_date?: string;
  reason?: string | null;
}): Promise<Closure> {
  return request<Closure>("/api/v1/salon/closures", { method: "POST", body });
}

export async function deleteClosure(id: string): Promise<void> {
  await request(`/api/v1/salon/closures/${id}`, { method: "DELETE" });
}

// ==================== PRESTATIONS (catalogue coiffeur) ====================

export interface Prestation {
  id: string;
  name: string;
  category: string;
  duration_minutes: number;
  price_cents: number;
  price_eur: number;
  description: string | null;
  is_active: boolean;
  sort_order: number;
}

export interface PrestationPayload {
  name: string;
  category?: string;
  duration_minutes?: number;
  price_cents?: number;
  description?: string | null;
  is_active?: boolean;
  sort_order?: number;
}

export async function listPrestations(): Promise<{ prestations: Prestation[]; total: number }> {
  return request("/api/v1/prestations");
}

export async function createPrestation(payload: PrestationPayload): Promise<Prestation> {
  return request<Prestation>("/api/v1/prestations", { method: "POST", body: payload });
}

export async function updatePrestation(
  id: string,
  payload: Partial<PrestationPayload>
): Promise<Prestation> {
  return request<Prestation>(`/api/v1/prestations/${id}`, { method: "PATCH", body: payload });
}

export async function deletePrestation(id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/v1/prestations/${id}`, { method: "DELETE" });
}

export async function seedCoiffeurTemplate(): Promise<{ prestations: number; knowledge: number }> {
  return request("/api/v1/prestations/seed-coiffeur", { method: "POST" });
}

// ==================== QUESTIONS EN ATTENTE (à traiter par le coiffeur) ====================

export interface PendingQuestion {
  id: string;
  question: string;
  origin: string;
  status: string;
  answer: string | null;
  conversation_id: string | null;
  created_at: string;
}

export async function listPendingQuestions(params: {
  conversation_id?: string;
  status?: "open" | "answered" | "dismissed" | "all";
} = {}): Promise<{ questions: PendingQuestion[]; total: number }> {
  const qs = new URLSearchParams();
  if (params.conversation_id) qs.set("conversation_id", params.conversation_id);
  if (params.status) qs.set("status", params.status);
  const s = qs.toString();
  return request(`/api/v1/pending-questions${s ? `?${s}` : ""}`);
}

export async function answerPendingQuestion(
  id: string,
  answer: string,
  saveToKb = false
): Promise<PendingQuestion> {
  return request<PendingQuestion>(`/api/v1/pending-questions/${id}/answer`, {
    method: "POST",
    body: { answer, save_to_kb: saveToKb },
  });
}

export async function dismissPendingQuestion(id: string): Promise<PendingQuestion> {
  return request<PendingQuestion>(`/api/v1/pending-questions/${id}/dismiss`, { method: "POST" });
}

// ==================== ASSISTANT DU COIFFEUR (chat gérant) ====================

export interface OwnerChatResponse {
  response: string;
  action: string;
  data: Record<string, unknown>;
}

export async function ownerChat(message: string): Promise<OwnerChatResponse> {
  return request<OwnerChatResponse>("/api/v1/owner/chat", { method: "POST", body: { message } });
}

// ==================== CHAT EN STREAMING (SSE) ====================

export interface StreamChatPayload {
  conversation_id: string;
  business_id: string;
  message: string;
  customer_id?: string | null;
  channel?: string;
  language?: string | null;
}

/**
 * Chat client en streaming : `onToken` est appelé au fil de l'eau (mot à mot),
 * `onDone` reçoit les métadonnées finales (intent, action_result…). La réponse
 * complète est déjà passée au garde-fou persona côté serveur avant diffusion.
 */
export async function streamChat(
  payload: StreamChatPayload,
  onToken: (token: string) => void,
  onDone: (meta: Record<string, unknown>) => void
): Promise<void> {
  const tok = getToken();
  const res = await fetch(`${API_BASE}/api/v1/conversation/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(tok ? { Authorization: `Bearer ${tok}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, res.statusText);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(line.slice(5).trim());
      } catch {
        continue; // ligne SSE partielle ou non-JSON : on ignore
      }
      // Erreur côté serveur → on lève pour que l'appelant bascule sur le fallback
      // (appel non-streamé), plutôt que de laisser une bulle vide.
      if (data.error) throw new ApiError(502, "stream_error", data);
      if (data.done) onDone(data);
      else if (typeof data.token === "string") onToken(data.token as string);
    }
  }
}

// ==================== HEALTH ====================

export async function checkHealth(): Promise<{ status: string }> {
  return request<{ status: string }>("/health");
}

// Readiness profonde : reflète exactement la forme renvoyée par `/ready`
// (health.py). Chaque check porte son propre `status` ("ok" | "warning" |
// "error" | "skip") + des champs spécifiques. Le endpoint répond 200 si prêt,
// 503 si dégradé — on lit le corps dans les deux cas.
export interface ReadinessCheck {
  status: "ok" | "warning" | "error" | "skip" | string;
  type?: string;
  error?: string;
  reason?: string;
  // ml_models expose en plus l'état de chaque modèle.
  intent_model?: string;
  ner_model?: string;
}

export interface Readiness {
  status: "ready" | "degraded" | string;
  env?: string;
  timestamp?: string;
  checks: {
    database: ReadinessCheck;
    redis: ReadinessCheck;
    ml_models: ReadinessCheck;
    [key: string]: ReadinessCheck;
  };
}

export async function getReadiness(): Promise<Readiness> {
  // `/ready` renvoie 503 quand le service est dégradé : on récupère quand même
  // le JSON (qui décrit quel check a échoué) plutôt que de lever une ApiError.
  const token = getToken();
  const res = await fetch(`${API_BASE}/ready`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new ApiError(res.status, res.statusText);
  }
  return data as Readiness;
}

// ==================== LLM (bascule de moteur) ====================

export interface LlmOption {
  key: string;
  label: string;
  hint: string;
  model: string;
  available: boolean;
  current: boolean;
}

export interface LlmState {
  active: string;
  options: LlmOption[];
}

export async function getLlmSettings(): Promise<LlmState> {
  return request<LlmState>("/api/v1/settings/llm");
}

export async function switchLlm(key: string): Promise<LlmState> {
  return request<LlmState>("/api/v1/settings/llm", { method: "POST", body: { key } });
}

// ==================== MODÈLE MAISON (NanoGPT from scratch) ====================

// Un point de la courbe d'entraînement (un palier de `step`).
export interface NanoGptTrainingPoint {
  step: number;
  train_loss: number;
  val_loss: number;
  lr: number;
  tokens_seen: number;
  elapsed_s: number;
}

// Hyperparamètres de l'architecture du GPT maison (null tant qu'il n'a pas tourné).
export interface NanoGptModelArch {
  n_layer: number;
  n_head: number;
  n_embd: number;
  block_size: number;
}

export interface NanoGptTraining {
  // « running » = entraînement en cours, « done » = terminé, « absent » = jamais lancé.
  state: "running" | "done" | "absent";
  points: NanoGptTrainingPoint[];
  step: number;
  max_steps: number;
  params: number;
  vocab_size: number;
  best_val_loss: number | null;
  device: string | null;
  total_tokens: number | null;
  model: NanoGptModelArch | null;
}

export async function getNanoGptTraining(): Promise<NanoGptTraining> {
  return request<NanoGptTraining>("/api/v1/nanogpt/training");
}

// Un échantillon question→réponse joué contre un modèle lors de la comparaison.
export interface ModelComparisonSample {
  q: string;
  a: string;
  ok: boolean;
}

// Résultat d'un modèle (Groq / Ollama / NanoGPT) sur le même jeu de prompts.
export interface ModelComparisonResult {
  key: string;
  label: string;
  provider: string;
  model: string;
  available: boolean;
  score_pct: number | null;
  checks_passed: number | null;
  checks_total: number | null;
  avg_latency_ms: number | null;
  note: string | null;
  samples?: ModelComparisonSample[];
}

export interface ModelComparison {
  generated_at: number | null;
  prompts: number;
  results: ModelComparisonResult[];
}

export async function getModelComparison(): Promise<ModelComparison> {
  return request<ModelComparison>("/api/v1/nanogpt/comparison");
}

export { ApiError, getToken, setToken, clearToken };
