import * as Primitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useRef, type ReactNode } from "react";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const previousFocus = useRef<HTMLElement | null>(null);
  return (
    <Primitive.Root open={open} onOpenChange={onOpenChange}>
      <Primitive.Portal>
        <Primitive.Overlay className="fixed inset-0 z-40 bg-black/35 backdrop-blur-xs" />
        <Primitive.Content
          onOpenAutoFocus={() => {
            previousFocus.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (previousFocus.current?.isConnected)
              previousFocus.current.focus();
          }}
          className="dialog-content fixed left-1/2 top-1/2 z-50 flex max-h-[90dvh] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-border bg-surface p-6 shadow-xl"
        >
          {/* 标题与说明固定，正文单独滚动，滚动条就不会压到关闭按钮和圆角。 */}
          <div className="dialog-head">
            <Primitive.Title className="pr-12 text-xl font-semibold">
              {title}
            </Primitive.Title>
            <Primitive.Description className="mt-2 text-sm text-secondary">
              {description}
            </Primitive.Description>
          </div>
          <div className="dialog-body">{children}</div>
          <Primitive.Close
            className="absolute right-4 top-4 inline-flex size-10 items-center justify-center rounded-lg hover:bg-muted"
            aria-label="关闭"
          >
            <X size={20} aria-hidden="true" />
          </Primitive.Close>
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
