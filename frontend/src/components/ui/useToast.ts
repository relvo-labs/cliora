import { readonly, ref } from "vue";

export type ToastKind = "success" | "info" | "warning" | "error";
export interface ToastMessage {
  id: number;
  kind: ToastKind;
  title: string;
  message?: string;
}

const messages = ref<ToastMessage[]>([]);
let nextId = 1;

function dismiss(id: number): void {
  messages.value = messages.value.filter((message) => message.id !== id);
}

function push(input: Omit<ToastMessage, "id">): number {
  const id = nextId++;
  messages.value.push({ id, ...input });
  if (input.kind !== "error") {
    window.setTimeout(() => dismiss(id), 6000);
  }
  return id;
}

export function useToast() {
  return { messages: readonly(messages), push, dismiss };
}
