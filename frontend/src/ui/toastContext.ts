import { createContext, useContext } from "react";

export type ToastKind = "success" | "info" | "error";

export interface ToastApi {
  show: (message: string, kind?: ToastKind) => void;
}

export const ToastContext = createContext<ToastApi>({ show: () => undefined });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
