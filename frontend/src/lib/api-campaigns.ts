import { request } from "./api";

// relances : segments, campagnes, trous

export type SegmentKey = "dormants" | "no_shows" | "nouveaux" | "fideles";

export interface Segment {
  key: SegmentKey;
  label: string;
  description: string;
  suggestion: string;
  count: number;
  reachable: number;
  eligible: number;
}

export interface SampleCustomer {
  id: string;
  name: string;
  visits: number;
  last_visit_at: string | null;
  no_shows: number;
  reachable: boolean;
  eligible: boolean;
}

export interface SegmentPreview extends Segment {
  sample: SampleCustomer[];
}

export interface RenderedMessage {
  text: string;
  length: number;
  sms_parts: number;
}

export interface Campaign {
  id: string;
  segment: SegmentKey;
  segment_label: string;
  message: string;
  status: "sending" | "sent" | string;
  created_at: string;
  created_by: string | null;
  target_count: number;
  sent_count: number;
  skipped_count: number;
  returned_count: number;
  revenue_eur: number;
  window_ends_at: string;
  window_open: boolean;
}

export interface CampaignHistory {
  summary: {
    campaigns: number;
    sent: number;
    returned: number;
    revenue_eur: number;
    return_rate_pct: number;
  };
  campaigns: Campaign[];
}

export interface GapsOverview {
  gaps: { start: string; label: string }[];
  candidates: number;
  planned: {
    name: string;
    source: "waitlist" | "rebook" | string;
    service: string | null;
    slot_start: string;
    label: string;
    duration_minutes: number;
  }[];
  sent_7d: number;
  failed_7d: number;
  filled_7d: number;
  in_send_hours: boolean;
}

export interface GapRun {
  sent: number;
  failed: number;
  planned: number;
  skipped: string | null;
}

export function listSegments(): Promise<Segment[]> {
  return request<Segment[]>("/api/v1/campaigns/segments");
}

export function previewSegment(key: SegmentKey, limit = 8): Promise<SegmentPreview> {
  return request<SegmentPreview>(`/api/v1/campaigns/segments/${key}?limit=${limit}`);
}

export function renderCampaignMessage(message: string, name?: string): Promise<RenderedMessage> {
  return request<RenderedMessage>("/api/v1/campaigns/render", {
    method: "POST",
    body: { message, name },
  });
}

export function sendCampaign(segment: SegmentKey, message: string): Promise<Campaign> {
  return request<Campaign>("/api/v1/campaigns", {
    method: "POST",
    body: { segment, message },
  });
}

export function getCampaignHistory(limit = 30): Promise<CampaignHistory> {
  return request<CampaignHistory>(`/api/v1/campaigns?limit=${limit}`);
}

export function getGaps(): Promise<GapsOverview> {
  return request<GapsOverview>("/api/v1/campaigns/gaps");
}

export function runGapFiller(): Promise<GapRun> {
  return request<GapRun>("/api/v1/campaigns/gaps/run", { method: "POST" });
}

export function setMarketingOptOut(
  customerId: string,
  optOut: boolean
): Promise<{ customer_id: string; opt_out: boolean; opt_out_at: string | null }> {
  return request(`/api/v1/campaigns/opt-out/${customerId}`, {
    method: "PUT",
    body: { opt_out: optOut },
  });
}
