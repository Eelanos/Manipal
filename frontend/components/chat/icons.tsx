// Tiny inline icons (no icon library in this project). All 20x20, stroke = currentColor.
import type { ReactNode } from "react";

function Svg({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {children}
    </svg>
  );
}

export const SparkIcon = ({ size }: { size?: number }) => (
  <Svg size={size}><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" /><path d="M19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7L19 16z" /></Svg>
);
export const ChatIcon = ({ size }: { size?: number }) => (
  <Svg size={size}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /></Svg>
);
export const PlusIcon = () => <Svg size={16}><path d="M12 5v14M5 12h14" /></Svg>;
export const ExpandIcon = () => <Svg size={16}><path d="M15 4h5v5M9 20H4v-5M20 4l-6 6M4 20l6-6" /></Svg>;
export const CompressIcon = () => <Svg size={16}><path d="M20 9h-5V4M4 15h5v5M15 9l6-6M9 15l-6 6" /></Svg>;
export const MinimizeIcon = () => <Svg size={16}><path d="M6 9l6 6 6-6" /></Svg>;
export const SendIcon = () => <Svg size={18}><path d="M5 12h14M13 6l6 6-6 6" /></Svg>;
export const StopIcon = () => <Svg size={16}><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" /></Svg>;
export const BulbIcon = () => <Svg size={16}><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" /></Svg>;
export const ArrowIcon = () => <Svg size={14}><path d="M7 17L17 7M9 7h8v8" /></Svg>;
export const CopyIcon = () => <Svg size={14}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></Svg>;
export const DownloadIcon = () => <Svg size={14}><path d="M12 4v11M7 11l5 5 5-5M5 20h14" /></Svg>;
