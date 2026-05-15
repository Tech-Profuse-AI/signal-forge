import { BookOpen, CircleHelp, MessageCircle, Radio } from 'lucide-react';

export const PLATFORM_META = {
  reddit: {
    label: 'Reddit',
    mark: 'R',
    icon: MessageCircle,
    accent: '#ff4500',
    softClass: 'bg-orange-500/10 text-orange-200 border-orange-300/20',
  },
  quora: {
    label: 'Quora',
    mark: 'Q',
    icon: CircleHelp,
    accent: '#b92b27',
    softClass: 'bg-red-500/10 text-red-200 border-red-300/20',
  },
  medium: {
    label: 'Medium',
    mark: 'M',
    icon: BookOpen,
    accent: '#17c964',
    softClass: 'bg-emerald-500/10 text-emerald-100 border-emerald-300/20',
  },
  unknown: {
    label: 'Unknown',
    mark: 'S',
    icon: Radio,
    accent: '#8b8fa3',
    softClass: 'bg-slate-500/10 text-slate-200 border-slate-300/20',
  },
};

export function getPlatformMeta(platform) {
  return PLATFORM_META[String(platform || '').toLowerCase()] || PLATFORM_META.unknown;
}

export function platformLabel(platform) {
  return getPlatformMeta(platform).label;
}
