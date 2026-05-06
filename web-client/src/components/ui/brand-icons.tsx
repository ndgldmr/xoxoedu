import type {JSX, SVGProps} from "react";

function BaseIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return <svg fill="none" viewBox="0 0 24 24" {...props} />;
}

export function LinkedInIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <BaseIcon aria-hidden="true" {...props}>
      <path
        d="M6.94 8.5H3.56V20h3.38V8.5Zm.22-3.56A1.96 1.96 0 1 1 3.24 4.94a1.96 1.96 0 0 1 3.92 0ZM20 13.02c0-3.46-2.21-4.74-4.3-4.74-1.68 0-2.72.93-3.17 1.58h-.05V8.5H9.24V20h3.38v-6.2c0-1.63.31-3.2 2.33-3.2 1.99 0 2.02 1.86 2.02 3.3V20H20v-6.98Z"
        fill="currentColor"
      />
    </BaseIcon>
  );
}

export function InstagramIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <BaseIcon aria-hidden="true" {...props}>
      <path
        d="M8.5 3h7A5.5 5.5 0 0 1 21 8.5v7a5.5 5.5 0 0 1-5.5 5.5h-7A5.5 5.5 0 0 1 3 15.5v-7A5.5 5.5 0 0 1 8.5 3Zm0 1.9A3.6 3.6 0 0 0 4.9 8.5v7a3.6 3.6 0 0 0 3.6 3.6h7a3.6 3.6 0 0 0 3.6-3.6v-7a3.6 3.6 0 0 0-3.6-3.6h-7Zm7.4 1.42a1.18 1.18 0 1 1 0 2.36 1.18 1.18 0 0 1 0-2.36ZM12 7.63A4.37 4.37 0 1 1 7.63 12 4.37 4.37 0 0 1 12 7.63Zm0 1.9A2.47 2.47 0 1 0 14.47 12 2.47 2.47 0 0 0 12 9.53Z"
        fill="currentColor"
      />
    </BaseIcon>
  );
}

export function TikTokIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <BaseIcon aria-hidden="true" {...props}>
      <path
        d="M14.6 3c.23 1.9 1.3 3.35 3.16 4.03.68.25 1.45.37 2.24.36v2.66a7.34 7.34 0 0 1-3.07-.68v4.8c0 3.8-3.06 6.83-6.84 6.83A6.82 6.82 0 0 1 3.6 13.2a6.83 6.83 0 0 1 9.34-6.35v2.86a4.14 4.14 0 0 0-2.05-.56 4.16 4.16 0 1 0 4.15 4.15V3h2.56Z"
        fill="currentColor"
      />
    </BaseIcon>
  );
}

export function WebsiteIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <BaseIcon aria-hidden="true" {...props}>
      <path
        d="M12 3a9 9 0 1 0 9 9 9.01 9.01 0 0 0-9-9Zm5.98 8h-2.7a15.13 15.13 0 0 0-1.4-5.12A7.05 7.05 0 0 1 17.98 11ZM12 4.9c.9 1.04 1.86 3.08 2.27 6.1H9.73C10.14 7.98 11.1 5.94 12 4.9ZM5.9 16A7 7 0 0 1 4.02 13h2.7c.1 1.06.29 2.06.58 3H5.9Zm.82-5H4.02A7 7 0 0 1 5.9 8h1.4a14.1 14.1 0 0 0-.58 3Zm1.92 0a12.33 12.33 0 0 1 .76-3h5.2c.36.94.62 1.95.76 3H8.64Zm0 2h6.72a12.34 12.34 0 0 1-.76 3h-5.2a12.33 12.33 0 0 1-.76-3ZM12 19.1c-.9-1.04-1.86-3.08-2.27-6.1h4.54c-.41 3.02-1.37 5.06-2.27 6.1ZM13.88 18.12A15.13 15.13 0 0 0 15.28 13h2.7a7.05 7.05 0 0 1-4.1 5.12Z"
        fill="currentColor"
      />
    </BaseIcon>
  );
}
