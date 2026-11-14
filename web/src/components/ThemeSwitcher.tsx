import { useTheme } from "next-themes";
import { Button } from "@heroui/react";
import { useEffect, useState } from "react";

export function ThemeSwitcher() {
    const { theme, setTheme } = useTheme();
    const [mounted, setMounted] = useState(false);

    useEffect(() => setMounted(true), []);

    if (!mounted) return null;

    return (
        <Button
            variant="secondary"
            onPress={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
            {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
        </Button>
    );
}