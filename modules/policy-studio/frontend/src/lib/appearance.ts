export const STUDIO_THEMES = [
  {
    id: 'black',
    label: 'Black',
    description: 'Deep neutral black with restrained contrast.',
    swatches: ['#07090d', '#11151b', '#252b34', '#9db4cf'],
  },
  {
    id: 'navy',
    label: 'Navy',
    description: 'The original UWflow blue-grey workspace.',
    swatches: ['#0b1017', '#121b26', '#263445', '#67aaf4'],
  },
  {
    id: 'pro-white',
    label: 'Pro White',
    description: 'Clean white surfaces with clear ink contrast.',
    swatches: ['#f7f9fc', '#ffffff', '#d6dee8', '#225f9c'],
  },
  {
    id: 'neat-silver',
    label: 'Neat Silver',
    description: 'Soft silver-grey surfaces with a muted blue accent.',
    swatches: ['#e7ebef', '#f4f6f8', '#c8d0d9', '#315f8d'],
  },
] as const

export type StudioTheme = (typeof STUDIO_THEMES)[number]['id']

export const TEXT_SIZES = [
  { id: 'compact', label: 'Compact', scale: 1 },
  { id: 'comfortable', label: 'Comfortable', scale: 1.15 },
  { id: 'large', label: 'Large', scale: 1.3 },
  { id: 'extra-large', label: 'Extra large', scale: 1.45 },
] as const

export type TextSize = (typeof TEXT_SIZES)[number]['id']

export interface StudioPreferences {
  theme: StudioTheme
  textSize: TextSize
}

export const DEFAULT_STUDIO_PREFERENCES: StudioPreferences = {
  theme: 'navy',
  textSize: 'comfortable',
}

const STORAGE_KEY = 'uwflow.policy-studio.appearance.v1'

function isTheme(value: unknown): value is StudioTheme {
  return STUDIO_THEMES.some((theme) => theme.id === value)
}

function isTextSize(value: unknown): value is TextSize {
  return TEXT_SIZES.some((size) => size.id === value)
}

export function loadStudioPreferences(): StudioPreferences {
  if (typeof window === 'undefined') return DEFAULT_STUDIO_PREFERENCES
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_STUDIO_PREFERENCES
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object') return DEFAULT_STUDIO_PREFERENCES
    const saved = value as Record<string, unknown>
    return {
      theme: isTheme(saved.theme) ? saved.theme : DEFAULT_STUDIO_PREFERENCES.theme,
      textSize: isTextSize(saved.textSize) ? saved.textSize : DEFAULT_STUDIO_PREFERENCES.textSize,
    }
  } catch {
    // Preferences are optional; blocked storage or malformed values use defaults.
    return DEFAULT_STUDIO_PREFERENCES
  }
}

export function saveStudioPreferences(preferences: StudioPreferences): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // The current session still uses the selected preferences when storage is unavailable.
  }
}
