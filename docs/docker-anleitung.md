# Docker-Anleitung für Einsteiger (Windows)

Diese Anleitung richtet sich an Nutzer, die noch keine Erfahrung mit Docker haben. Sie erklärt Schritt für Schritt, wie Docker Desktop unter Windows installiert wird und wie damit die lokale PostgreSQL-Datenbank für die Sport Dashboard API gestartet wird.

**Docker ist optional:** Für die Entwicklung kann stattdessen eine separate Neon-DEV-Datenbank verwendet werden. Dann sind Docker Desktop und die Befehle in dieser Anleitung nicht erforderlich. Siehe [entwicklung.md](entwicklung.md).

---

## Was ist Docker und wofür können wir es nutzen?

Docker ist eine Software, mit der man Anwendungen in sogenannten **Containern** ausführen kann. Ein Container ist eine isolierte, leichtgewichtige Laufzeitumgebung – ähnlich einer kleinen virtuellen Maschine, aber ohne das gesamte Betriebssystem.

**Warum nutzen wir Docker hier?**
Anstatt PostgreSQL lokal auf Windows zu installieren (was aufwendig und fehleranfällig sein kann), starten wir die Datenbank einfach als Docker-Container. So bleibt das System sauber, und die Datenbank kann mit einem einzigen Befehl gestartet oder entfernt werden.

Konkret starten wir zwei Container:
- **postgres** – die PostgreSQL-Datenbank (Port 5432)
- **pgadmin** – eine Web-Oberfläche zur Datenbank-Verwaltung (Port 5050)

---

## Schritt 1: WSL2 aktivieren (Voraussetzung)

Docker Desktop unter Windows benötigt **WSL2** (Windows Subsystem for Linux 2). Falls WSL2 noch nicht eingerichtet ist:

1. Öffne eine **PowerShell als Administrator** (Rechtsklick auf das Startmenü → „Windows PowerShell (Administrator)").
2. Führe folgenden Befehl aus:

   ```powershell
   wsl --install
   ```

3. Starte den Computer **neu**, wenn du dazu aufgefordert wirst.
4. Nach dem Neustart öffnet sich automatisch ein Fenster zur Einrichtung von Ubuntu. Du kannst es schließen – du benötigst Ubuntu selbst nicht, nur WSL2 als Unterbau für Docker.

Falls WSL2 bereits installiert ist, kannst du diesen Schritt überspringen.

---

## Schritt 2: Docker Desktop installieren

1. Öffne im Browser: [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
2. Klicke auf **„Download Docker Desktop for Windows"**.
3. Starte das heruntergeladene Installationsprogramm (`Docker Desktop Installer.exe`).
4. Im Installationsdialog:
   - Stelle sicher, dass **„Use WSL 2 instead of Hyper-V"** aktiviert ist (sollte standardmäßig aktiv sein).
   - Klicke auf **„OK"** / **„Install"**.
5. Warte, bis die Installation abgeschlossen ist.
6. **Starte den Computer neu**, wenn die Installation es verlangt.
7. Nach dem Neustart startet Docker Desktop automatisch. Das Docker-Symbol erscheint in der Taskleiste (Systray, rechts unten).

---

## Schritt 3: Installation überprüfen

Öffne eine **PowerShell** (normaler Benutzer, kein Admin nötig) und führe folgende Befehle aus:

```powershell
docker --version
```

Erwartete Ausgabe (Versionsnummer kann abweichen):
```
Docker version 27.x.x, build xxxxxxx
```

```powershell
docker compose version
```

Erwartete Ausgabe:
```
Docker Compose version v2.x.x
```

Wenn beide Befehle eine Versionsnummer ausgeben, ist Docker korrekt installiert.

> **Hinweis:** Docker Desktop muss **gestartet sein**, bevor du Docker-Befehle ausführen kannst. Prüfe, ob das Docker-Symbol in der Taskleiste sichtbar ist und kein Warnzeichen trägt.

---

## Schritt 4: Projekt-Datenbank starten

1. Öffne eine **PowerShell** und wechsle in den Projekt-Root:

   ```powershell
   cd "C:\Users\ihmel\Documents\Programmier Projekte\Sport_Dashboard_API"
   ```

   *(Passe den Pfad an deinen Speicherort an.)*

2. Starte die Container im Hintergrund:

   ```powershell
   docker compose up -d
   ```

   **Was passiert dabei?**
   - Docker liest die Datei `docker-compose.yml` im aktuellen Verzeichnis.
   - Es werden zwei Container erstellt und gestartet:
     - `sport_postgres` – PostgreSQL-Datenbank (Benutzer: `sport`, Passwort: `sport`, Datenbank: `sportdb`, Port: `5432`)
     - `sport_pgadmin` – pgAdmin-Weboberfläche (Port: `5050`)
   - Das Flag `-d` steht für „detached" – die Container laufen im Hintergrund weiter, auch wenn du das Terminal schließt.
   - Beim ersten Start lädt Docker die benötigten Images herunter (ca. 200–400 MB). Das kann einige Minuten dauern.

3. Überprüfe, ob die Container laufen:

   ```powershell
   docker ps
   ```

   Du solltest beide Container in der Liste sehen, mit Status `Up`:

   ```
   CONTAINER ID   IMAGE            COMMAND                  STATUS         PORTS
   xxxxxxxxxxxx   postgres:16      "docker-entrypoint.s…"   Up 30 seconds  0.0.0.0:5432->5432/tcp
   xxxxxxxxxxxx   dpage/pgadmin4   "/entrypoint.sh"         Up 30 seconds  0.0.0.0:5050->80/tcp
   ```

---

## Schritt 5: pgAdmin öffnen und Datenbank verbinden

**pgAdmin** ist eine grafische Oberfläche zur Verwaltung von PostgreSQL-Datenbanken.

1. Öffne im Browser: [http://localhost:5050](http://localhost:5050)
2. **Anmeldedaten:**
   - E-Mail: `admin@example.com`
   - Passwort: `admin`
3. Klicke nach dem Login auf **„Add New Server"** (oder Rechtsklick auf „Servers" im linken Baum → „Register" → „Server…").
4. Im Dialog **„Register – Server"**:

   **Tab „General":**
   - Name: `SportDB` (beliebig, nur zur Anzeige)

   **Tab „Connection":**
   - Host name/address: `postgres`
     *(Innerhalb des Docker-Netzwerks ist der PostgreSQL-Container unter dem Namen `postgres` erreichbar. Alternativ funktioniert außerhalb von Docker: `host.docker.internal` oder `localhost`.)*
   - Port: `5432`
   - Maintenance database: `sportdb`
   - Username: `sport`
   - Password: `sport`
   - Häkchen bei **„Save password"** setzen.

5. Klicke auf **„Save"**. pgAdmin verbindet sich mit der Datenbank.

> **Hinweis – Hostname innerhalb vs. außerhalb Docker:**
> - `postgres` funktioniert, wenn pgAdmin selbst als Docker-Container läuft (was hier der Fall ist). Die Container kommunizieren im selben Docker-Netzwerk.
> - `localhost` oder `host.docker.internal` würde man verwenden, wenn man sich von außerhalb Docker (z. B. von einem lokalen Tool auf Windows) mit der Datenbank verbindet.
> - Bei Nutzung der **Docker-Datenbank** muss `DATABASE_URL` in deiner `.env` auf `localhost:5432` zeigen, weil die Python-App direkt auf Windows läuft. Eine Neon-URL verbindet dagegen weiterhin mit Neon, auch wenn die Docker-Container gestartet sind. Die lokale URL steht in `.env.example`.

---

## Container verwalten

### Container stoppen (Daten bleiben erhalten)

```powershell
docker compose stop
```

Die Container werden angehalten. Beim nächsten `docker compose up -d` starten sie wieder, und alle Daten sind noch vorhanden.

### Container entfernen (Daten bleiben erhalten)

```powershell
docker compose down
```

Die Container werden gestoppt und entfernt. Die Daten in der Datenbank bleiben erhalten, weil sie in einem **Docker Volume** gespeichert sind.

### Container und alle Daten löschen

```powershell
docker compose down -v
```

> **Achtung:** Das Flag `-v` löscht auch die Volumes – alle Datenbankdaten werden unwiderruflich gelöscht. Nur ausführen, wenn du einen sauberen Neustart möchtest.

---

## Häufige Fehler und Lösungen

### Fehler: Port 5432 ist bereits belegt

```
Error response from daemon: Ports are not available: ... 0.0.0.0:5432: bind: An attempt was made to access a socket in a way forbidden by its access permissions.
```

**Ursache:** Eine andere Anwendung (z. B. eine lokale PostgreSQL-Installation) belegt bereits Port 5432.

**Lösung:**
- Prüfe, welcher Prozess den Port belegt: `netstat -ano | findstr :5432`
- Beende den Prozess oder ändere in der `docker-compose.yml` den Host-Port (z. B. `5433:5432`). Passe dann auch `DATABASE_URL` in der `.env` entsprechend an (`localhost:5433`).

---

### Fehler: WSL2 ist nicht aktiviert

```
Hardware assisted virtualization and data execution protection must be enabled in the BIOS.
```

oder Docker Desktop zeigt beim Start einen WSL2-Fehler.

**Lösung:**
- Führe `wsl --install` in einer Admin-PowerShell aus (siehe Schritt 1).
- Stelle sicher, dass Virtualisierung im BIOS aktiviert ist (meistens standardmäßig aktiv auf modernen PCs).
- Starte den Computer nach der WSL2-Installation neu.

---

### Fehler: Docker Desktop ist nicht gestartet

```
error during connect: ... Is the docker daemon running?
```

**Lösung:**
- Öffne Docker Desktop über das Startmenü oder das Taskleisten-Symbol.
- Warte, bis Docker vollständig gestartet ist (das Symbol in der Taskleiste zeigt keinen Lade-Fortschritt mehr).
- Versuche den Befehl erneut.

---

### pgAdmin lädt nicht (http://localhost:5050 nicht erreichbar)

**Lösung:**
- Prüfe mit `docker ps`, ob der `sport_pgadmin`-Container läuft.
- Falls nicht: `docker compose up -d`
- Warte ca. 10–15 Sekunden nach dem Start, bevor du die Seite aufrufst (pgAdmin braucht etwas zum Hochfahren).
- Prüfe, ob Port 5050 durch eine Firewall blockiert wird.
