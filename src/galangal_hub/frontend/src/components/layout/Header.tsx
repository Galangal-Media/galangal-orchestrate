import { Link, useLocation } from "react-router-dom"
import { Moon, Sun, Menu, X, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/hooks/useTheme"
import { cn } from "@/lib/utils"
import { useState, useEffect } from "react"
import { GalangalLogo } from "@/components/GalangalLogo"

const navItems = [
  { path: "/", label: "Dashboard" },
  { path: "/agents", label: "Agents" },
  { path: "/tasks", label: "Tasks" },
  { path: "/environments", label: "Environments" },
  { path: "/ai-keys", label: "AI Keys" },
  { path: "/profiles", label: "Profiles" },
]

export function Header() {
  const { theme, toggleTheme } = useTheme()
  const location = useLocation()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [authRequired, setAuthRequired] = useState(false)

  // Check if auth is required
  useEffect(() => {
    fetch('/api/auth/status')
      .then(res => res.json())
      .then(data => setAuthRequired(data.auth_required))
      .catch(() => setAuthRequired(false))
  }, [])

  const handleLogout = () => {
    window.location.href = '/logout'
  }

  return (
    <header className="sticky top-0 z-50 w-full border-b border-header-border bg-header/95 backdrop-blur supports-[backdrop-filter]:bg-header/80">
      <div className="container flex h-18 items-center py-3">
        <div className="mr-4 flex">
          <Link to="/" className="mr-8 flex items-center gap-2.5 group">
            <GalangalLogo size={48} />
            <span className="font-bold text-base text-primary tracking-tight">
              Galangal Hub
            </span>
          </Link>
          <nav className="hidden md:flex items-center gap-0.5 text-sm font-medium">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "px-3.5 py-1.5 rounded-md transition-colors duration-150",
                  location.pathname === item.path
                    ? "text-foreground bg-muted"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex flex-1 items-center justify-end gap-1.5">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="rounded-lg hover:bg-muted"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4 text-muted-foreground" />
            ) : (
              <Moon className="h-4 w-4 text-muted-foreground" />
            )}
          </Button>
          {authRequired && (
            <Button
              variant="ghost"
              size="icon"
              onClick={handleLogout}
              aria-label="Logout"
              className="rounded-lg hover:bg-muted"
              title="Logout"
            >
              <LogOut className="h-4 w-4 text-muted-foreground" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden rounded-lg hover:bg-muted"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? (
              <X className="h-4 w-4 text-muted-foreground" />
            ) : (
              <Menu className="h-4 w-4 text-muted-foreground" />
            )}
          </Button>
        </div>
      </div>
      {/* Mobile menu */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-header-border bg-header animate-fade-in">
          <nav className="flex flex-col gap-1 p-4">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setMobileMenuOpen(false)}
                className={cn(
                  "px-4 py-3 rounded-lg transition-colors duration-150 font-medium",
                  location.pathname === item.path
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                )}
              >
                {item.label}
              </Link>
            ))}
            {authRequired && (
              <button
                onClick={handleLogout}
                className="px-4 py-3 rounded-lg transition-colors duration-150 font-medium text-left text-muted-foreground hover:text-foreground hover:bg-muted/50 flex items-center gap-2"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </button>
            )}
          </nav>
        </div>
      )}
    </header>
  )
}
