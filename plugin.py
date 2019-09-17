import sys

import subprocess
import struct
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from os import listdir, environ

from dataclasses import dataclass

from urllib.parse import parse_qs, urlparse

from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.types import Game, LicenseInfo, LicenseType, Authentication, LocalGame, NextStep
from galaxy.api.consts import Platform, LocalGameState

# Manually override if you dare
roms_path = ""
emulator_path = ""

class AuthenticationHandler(BaseHTTPRequestHandler):
    def _set_headers(self, content_type='text/html'):
        self.send_response(200)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def do_GET(self):
        if "setpath" in self.path:
            self._set_headers()
            parse_result = urlparse(self.path)
            params = parse_qs(parse_result.query)
            global roms_path, emulator_path
            roms_path = params['path'][0]
            emulator_path = params['emulator_path'][0]
            self.wfile.write("<script>window.location=\"/end\";</script>".encode("utf8"))
            return

        self._set_headers()
        self.wfile.write("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Citra Integration</title>
            <link href="https://fonts.googleapis.com/css?family=Lato:300&display=swap" rel="stylesheet"> 
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bulma/0.7.5/css/bulma.min.css" integrity="sha256-vK3UTo/8wHbaUn+dTQD0X6dzidqc5l7gczvH+Bnowwk=" crossorigin="anonymous" />
            <style>
                @charset "UTF-8";
                html, body {
                    padding: 0;
                    margin: 0;
                    border: 0;
                    background: rgb(40, 39, 42) !important;
                }
                
                html {
                    font-size: 12px;
                    line-height: 1.5;
                    font-family: 'Lato', sans-serif;
                }

                html {
                    overflow: scroll;
                    overflow-x: hidden;
                }
                ::-webkit-scrollbar {
                    width: 0px;  /* Remove scrollbar space */
                    background: transparent;  /* Optional: just make scrollbar invisible */
                }

                .header {
                    background: rgb(46, 45, 48);
                    height: 66px;
                    line-height: 66px;
                    font-weight: 600;
                    text-align: center;
                    vertical-align: middle;
                    padding: 0;
                    margin: 0;
                    border: 0;
                    font-size: 16px;
                    box-sizing: border-box;
                    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
                    color: white !important;
                }
                
                .sub-container {
                    width: 90%;
                    min-width: 200px;
                }
            </style>
        </head>
        <body>
            <div class="header">
                Citra Plugin Configuration
            </div>
            
            <br />
            
            <div class="sub-container container">
                <form method="GET" action="/setpath">
                    <div class="field">
                      <label class="label has-text-light">Games Location</label>
                      <div class="control">
                        <input class="input" name="path" type="text" class="has-text-light" placeholder="Enter absolute Games path">
                      </div>
                    </div>

                    <div class="field">
                      <label class="label has-text-light">Citra Location</label>
                      <div class="control">
                        <input class="input" name="emulator_path" type="text" class="has-text-light" placeholder="Enter absolute Citra path">
                      </div>
                    </div>

                    <div class="field is-grouped">
                      <div class="control">
                        <input type="submit" class="button is-link" value="Enable Plugin" />
                      </div>
                    </div>
                </form>
            </div>
        </body>
        </html>
        """.encode('utf8'))


class AuthenticationServer(threading.Thread):
    def __init__(self, port = 0):
        super().__init__()
        self.path = ""
        server_address = ('localhost', port)
        self.httpd = HTTPServer(server_address, AuthenticationHandler)#partial(AuthenticationHandler, self))
        self.port = self.httpd.server_port

    def run(self):
        self.httpd.serve_forever()


class CitraPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(
            Platform.Nintendo3Ds,  # Choose platform from available list
            "0.2",  # Version
            reader,
            writer,
            token
        )
        self.games = []
        self.server = AuthenticationServer()
        self.server.start()

    def parse_games(self):
        self.games = get_games(roms_path)

    def shutdown(self):
        self.server.httpd.shutdown()

    async def launch_game(self, game_id):
        from os.path import join
        # Find game - lookup table would be good :P
        for game in self.games:
            if game.program_id == game_id:
                subprocess.Popen([emulator_path + "/citra-qt.exe", game.path])
                break
        return

    def finish_login(self):
        some_dict = dict()
        some_dict["roms_path"] = roms_path
        some_dict["emulator_path"] = emulator_path
        self.store_credentials(some_dict)

        self.parse_games()
        return Authentication(user_id="a_high_quality_citra_user", user_name=roms_path)

    # implement methods
    async def authenticate(self, stored_credentials=None):
        global roms_path, emulator_path
        # See if we have the path in the cache
        if len(roms_path) == 0 and stored_credentials is not None and "roms_path" in stored_credentials:
            roms_path = stored_credentials["roms_path"]

        if len(emulator_path) == 0 and stored_credentials is not None and "emulator_path" in stored_credentials:
            emulator_path = stored_credentials["emulator_path"]

        if len(roms_path) == 0 or len(emulator_path) == 0:
            PARAMS = {
                "window_title": "Configure Citra Plugin",
                "window_width": 400,
                "window_height": 300,
                "start_uri": "http://localhost:" + str(self.server.port),
                "end_uri_regex": ".*/end.*"
            }
            return NextStep("web_session", PARAMS)

        return self.finish_login()

    async def pass_login_credentials(self, step, credentials, cookies):
        return self.finish_login()

    async def get_owned_games(self):
        owned_games = []
        for game in self.games:
            license_info = LicenseInfo(LicenseType.OtherUserLicense, None)
            owned_games.append(Game(game_id=game.program_id, game_title=game.game_title, dlcs=None,
                        license_info=license_info))

        return owned_games

    async def get_local_games(self):
        local_games = []
        for game in self.games:
            local_game = LocalGame(game.program_id, LocalGameState.Installed)
            local_games.append(local_game)
        return local_games


@dataclass
class NCCHGame():
    program_id: str
    game_title: str
    path: str


def probe_game(path):
    with open(path, 'rb') as f:
        print("Reading:", path)
        f.seek(0x100)
        if f.read(4) != b'NCSD':
            print(path, "doesn't have a NCSD partition table")
            return None

        # Read partition table
        print("Found NCSD partition table")
        f.seek(0x120)
        partition_entry = struct.unpack('ii', f.read(8))
        ncch_offset = partition_entry[0] * 0x200
        ncch_size = partition_entry[1] * 0x200
        print("Game data partition offset:", ncch_offset)
        print("Game data partition size:", ncch_size)

        # Read program ID
        f.seek(ncch_offset + 0x150)
        program_id = f.read(10).decode('ascii')
        print("Program ID:", program_id)

        # Read ExeFS Region Offset
        f.seek(ncch_offset + 0x1A0)
        exefs_offset = struct.unpack('i', f.read(4))[0] * 0x200
        exefs_abs_offset = ncch_offset + exefs_offset
        print("Logo region:", exefs_offset)
        print("Logo absolute pointer:", exefs_abs_offset)

        # Read files
        f.seek(exefs_abs_offset)
        files = dict()
        for i in range(10):
            file_name = f.read(8).decode('ascii').replace('\0', '')
            if len(file_name) == 0:
                continue
            file_offset = struct.unpack('i', f.read(4))[0] + exefs_abs_offset + 0x200  # header offset
            file_size = struct.unpack('i', f.read(4))[0]
            print("Found file:", file_name, "at", file_offset)
            files[file_name] = file_offset

        # Get icon
        if "icon" not in files:
            print(path, "missing exefs://logo")
            return None

        icon_offset = files["icon"]
        f.seek(icon_offset)

        if f.read(4) != b'SMDH':
            print(path, "has invalid SMDH file")
            return

        f.seek(icon_offset + 0x8)

        # Read application title structs
        title_structs = []
        for i in range(12):
            short_desc = f.read(0x80).decode("utf-16").replace('\0', '')
            long_desc = f.read(0x100).decode("utf-16").replace('\0', '').replace('\n', ' ').replace('  ', ' ')
            publisher = f.read(0x80).decode("utf-16").replace('\0', '')
            title_structs.append(long_desc)

        # Check if English title is valid
        title = ""
        if len(title_structs[1]) > 0:
            title = title_structs[1]
        else:
            print("No English title for", path, "- using Japanese")
            title = title_structs[0]

        print(path, "=", title, "(", program_id, ")")
        return NCCHGame(program_id=program_id, game_title=title, path=path)


def get_files_in_dir(path):
    from os.path import isfile, join
    from os import walk
    files = walk(path)
    games_path = []
    for root, dirs, files in walk(path):
        for file in files:
            games_path.append(join(root, file))
    return games_path


def get_games(path):
    games_path = get_files_in_dir(path)
    games = []
    for game_path in games_path:
        game = probe_game(game_path)
        if game is not None:
            games.append(game)
    return games


def main():
    create_and_run_plugin(CitraPlugin, sys.argv)


# run plugin event loop
if __name__ == "__main__":
    main()
