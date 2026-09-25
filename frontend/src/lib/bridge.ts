// Интеграция с VK Mini Apps: инициализация, тема клиента, скачивание файлов и шеринг.
import bridge from "@vkontakte/vk-bridge";

const params = new URLSearchParams(window.location.search);

/** Запуск внутри ВКонтакте (веб-вью клиента или iframe на vk.com). */
export const inVK: boolean = params.has("vk_app_id") || params.has("vk_platform") || bridge.isEmbedded();

export const vkPlatform: string | null = params.get("vk_platform");

type Scheme = "light" | "dark";

export function initBridge(onScheme: (s: Scheme) => void): void {
  if (!inVK) return;
  bridge.subscribe((e) => {
    if (e.detail.type === "VKWebAppUpdateConfig") {
      const d = e.detail.data as { appearance?: string; scheme?: string };
      const s = d.appearance ?? (String(d.scheme ?? "").includes("dark") || d.scheme === "space_gray" ? "dark" : "light");
      onScheme(s === "dark" ? "dark" : "light");
    }
  });
  bridge.send("VKWebAppInit").catch(() => undefined);
}

const absolute = (u: string) => new URL(u, window.location.href).toString();

/** Скачивание: в мини-приложении — нативным методом клиента, в браузере — через ссылку. */
export async function downloadFile(href: string, filename: string): Promise<void> {
  if (inVK) {
    try {
      if (await bridge.supportsAsync("VKWebAppDownloadFile")) {
        await bridge.send("VKWebAppDownloadFile", { url: absolute(href), filename });
        return;
      }
    } catch {
      /* падаем в обычное скачивание */
    }
  }
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export async function shareLink(link: string): Promise<boolean> {
  if (inVK) {
    try {
      await bridge.send("VKWebAppShare", { link: absolute(link) });
      return true;
    } catch {
      return false;
    }
  }
  try {
    if (navigator.share) {
      await navigator.share({ url: absolute(link) });
      return true;
    }
    await navigator.clipboard.writeText(absolute(link));
    return true;
  } catch {
    return false;
  }
}

export function haptic(kind: "light" | "medium" = "light"): void {
  if (!inVK) return;
  bridge.send("VKWebAppTapticImpactOccurred", { style: kind }).catch(() => undefined);
}
