import "./globals.css";
export const metadata = {
  title: "ShortForge",
  description: "AI-assisted short-form video editor",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
