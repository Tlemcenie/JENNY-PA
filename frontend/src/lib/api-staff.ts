// client api équipe (coiffeurs)
import { request, type Appointment, type AppointmentCreatePayload } from "./api";

// mon..sun -> [début, fin] ou null (jour off)
export type StaffHours = Record<string, [string, string] | null>;

export interface StaffMember {
  id: string;
  display_name: string;
  color: string | null;
  is_active: boolean;
  working_hours: StaffHours | null; // null = horaires du salon
  prestation_ids: string[]; // vide = sait tout faire
  upcoming_count: number;
}

export interface StaffPayload {
  display_name?: string;
  color?: string | null;
  is_active?: boolean;
  working_hours?: StaffHours | null;
  prestation_ids?: string[];
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

export async function setStaffSkills(id: string, prestationIds: string[]): Promise<StaffMember> {
  return request<StaffMember>(`/api/v1/staff/${id}/skills`, {
    method: "PUT",
    body: { prestation_ids: prestationIds },
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
  payload: AppointmentCreatePayload & { staff_id?: string | null; auto_assign_staff?: boolean }
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
