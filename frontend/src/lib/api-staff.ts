// client api équipe (coiffeurs)
import {
  request,
  type Appointment,
  type AppointmentCreatePayload,
  type BookingBusinessInfo,
  type BookingConfirmation,
  type BookingRequestPayload,
  type BookingSlot,
  type BookingSlotsResponse,
} from "./api";

// mon..sun -> [début, fin] ou null (jour off)
export type StaffHours = Record<string, [string, string] | null>;

export interface StaffMember {
  id: string;
  display_name: string;
  color: string | null;
  is_active: boolean;
  working_hours: StaffHours | null; // null = horaires du salon
  all_services: boolean; // false = seulement prestation_ids
  prestation_ids: string[];
  upcoming_count: number;
}

export interface StaffPayload {
  display_name?: string;
  color?: string | null;
  is_active?: boolean;
  working_hours?: StaffHours | null;
  prestation_ids?: string[];
  all_services?: boolean;
}

export interface StaffLoad {
  staff_id: string;
  display_name: string;
  color: string | null;
  booked_minutes: number;
  available_minutes: number;
  fill_rate: number; // 0..1
}

// rdv avec son coiffeur
export interface StaffAppointment extends Appointment {
  staff_id?: string | null;
  staff_name?: string | null;
  staff_color?: string | null;
}

/** Sait tout faire ? */
export function doesEverything(m: Pick<StaffMember, "all_services" | "prestation_ids">): boolean {
  return m.all_services && m.prestation_ids.length === 0;
}

export async function listStaff(): Promise<{ staff: StaffMember[]; total: number }> {
  return request("/api/v1/staff");
}

export async function createStaff(
  payload: StaffPayload & { display_name: string }
): Promise<StaffMember> {
  return request<StaffMember>("/api/v1/staff", { method: "POST", body: payload });
}

export async function updateStaff(id: string, payload: StaffPayload): Promise<StaffMember> {
  return request<StaffMember>(`/api/v1/staff/${id}`, { method: "PATCH", body: payload });
}

export async function setStaffSkills(
  id: string,
  prestationIds: string[],
  allServices?: boolean
): Promise<StaffMember> {
  return request<StaffMember>(`/api/v1/staff/${id}/skills`, {
    method: "PUT",
    body: { prestation_ids: prestationIds, all_services: allServices },
  });
}

export async function deleteStaff(
  id: string
): Promise<{ status: "deleted" | "deactivated"; id: string }> {
  return request(`/api/v1/staff/${id}`, { method: "DELETE" });
}

export async function getStaffOccupancy(
  days = 7
): Promise<{ days: number; staff: StaffLoad[] }> {
  return request(`/api/v1/staff/occupancy?days=${days}`);
}

// crée un rdv (coiffeur choisi ou auto)
export async function createAppointmentWithStaff(
  payload: AppointmentCreatePayload & {
    staff_id?: string | null;
    auto_assign_staff?: boolean;
    prestation_id?: string | null;
  }
): Promise<StaffAppointment> {
  return request<StaffAppointment>("/api/v1/appointments", { method: "POST", body: payload });
}

// change le coiffeur d'un rdv
export async function setAppointmentStaff(
  id: string,
  staffId: string | null
): Promise<StaffAppointment> {
  return request<StaffAppointment>(`/api/v1/appointments/${id}`, {
    method: "PATCH",
    body: { staff_id: staffId },
  });
}

// ── réservation publique avec coiffeurs ──

export interface PublicStaff {
  id: string;
  display_name: string;
  prestation_ids: string[] | null; // null = tout
}

export interface PublicPrestation {
  id: string;
  name: string;
  category: string;
  duration_minutes: number;
  price_cents: number | null; // null = sur demande
}

export interface PublicBookingInfoFull extends BookingBusinessInfo {
  phone?: string | null;
  staff?: PublicStaff[];
  prestations?: PublicPrestation[];
}

export interface PublicSlot extends BookingSlot {
  staff_ids?: string[];
}

export interface PublicBookingConfirmation extends BookingConfirmation {
  staff_id?: string | null;
  staff_name?: string | null;
  prestation_name?: string | null;
}

/** Ce coiffeur fait-il cette prestation ? */
export function staffCanDo(member: PublicStaff, prestationId: string | null): boolean {
  if (!prestationId || member.prestation_ids === null) return true;
  return member.prestation_ids.includes(prestationId);
}

// toujours frais, jamais du cache
export async function getPublicBookingInfo(slug: string): Promise<PublicBookingInfoFull> {
  return request<PublicBookingInfoFull>(`/api/v1/public/booking/${encodeURIComponent(slug)}`, {
    cache: "no-store",
  });
}

export async function getPublicSlots(
  slug: string,
  dateIso: string,
  opts: { duration?: number; staffId?: string | null; prestationId?: string | null } = {}
): Promise<BookingSlotsResponse & { slots: PublicSlot[] }> {
  const qs = new URLSearchParams({ date: dateIso, duration: String(opts.duration ?? 30) });
  if (opts.staffId) qs.set("staff_id", opts.staffId);
  if (opts.prestationId) qs.set("prestation_id", opts.prestationId);
  return request(`/api/v1/public/booking/${encodeURIComponent(slug)}/slots?${qs.toString()}`);
}

export async function createPublicBooking(
  slug: string,
  payload: BookingRequestPayload & { staff_id?: string | null; prestation_id?: string | null }
): Promise<PublicBookingConfirmation> {
  return request<PublicBookingConfirmation>(
    `/api/v1/public/booking/${encodeURIComponent(slug)}/book`,
    { method: "POST", body: payload }
  );
}
