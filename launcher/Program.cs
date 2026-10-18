using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

namespace TuneMusicLauncher
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string serverUrl = "http://127.0.0.1:8000/";
                string statusUrl = "http://127.0.0.1:8000/api/license/status";

                // 1. Verificar se o servidor já está rodando
                bool isRunning = IsServerOnline(statusUrl);

                if (!isRunning)
                {
                    // Localizar pythonw.exe (silencioso, sem janela de terminal)
                    string pythonPath = "";
                    string[] candidatePythons = new string[]
                    {
                        Path.Combine(baseDir, "runtime", "pythonw.exe"),
                        Path.Combine(baseDir, "runtime", "python.exe"),
                        Path.Combine(baseDir, ".venv", "Scripts", "pythonw.exe"),
                        Path.Combine(baseDir, ".venv", "Scripts", "python.exe"),
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "uv", "python", "cpython-3.12-windows-x86_64-none", "pythonw.exe"),
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "uv", "python", "cpython-3.12-windows-x86_64-none", "python.exe")
                    };

                    foreach (var p in candidatePythons)
                    {
                        if (File.Exists(p))
                        {
                            pythonPath = p;
                            break;
                        }
                    }

                    if (string.IsNullOrEmpty(pythonPath))
                    {
                        MessageBox.Show("Motor Python não localizado no diretório do tunemusic Pro.\nPor favor, reinstale a aplicação.", "tunemusic Pro - Erro", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return;
                    }

                    string serverScript = Path.Combine(baseDir, "server.py");
                    if (!File.Exists(serverScript))
                    {
                        MessageBox.Show("Arquivo de inicialização (server.py) não encontrado.", "tunemusic Pro - Erro", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return;
                    }

                    // Iniciar servidor em segundo plano 100% invisível
                    ProcessStartInfo psiServer = new ProcessStartInfo
                    {
                        FileName = pythonPath,
                        Arguments = "\"" + serverScript + "\"",
                        WorkingDirectory = baseDir,
                        CreateNoWindow = true,
                        UseShellExecute = false,
                        WindowStyle = ProcessWindowStyle.Hidden
                    };

                    // Configurar PYTHONPATH para carregar pacotes locais
                    string sitePackages = Path.Combine(baseDir, ".venv", "Lib", "site-packages");
                    if (Directory.Exists(sitePackages))
                    {
                        psiServer.EnvironmentVariables["PYTHONPATH"] = sitePackages;
                    }

                    Process.Start(psiServer);

                    // Aguardar o servidor responder (timeout 12 segundos)
                    int attempts = 0;
                    while (attempts < 24 && !IsServerOnline(statusUrl))
                    {
                        Thread.Sleep(500);
                        attempts++;
                    }
                }

                // 2. Abrir Janela Desktop Nativa via Microsoft Edge ou Google Chrome (Modo Standalone App)
                string edgePath = @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe";
                if (!File.Exists(edgePath))
                {
                    edgePath = @"C:\Program Files\Microsoft\Edge\Application\msedge.exe";
                }

                string chromePath = @"C:\Program Files\Google\Chrome\Application\chrome.exe";
                if (!File.Exists(chromePath))
                {
                    chromePath = @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe";
                }

                string targetBrowser = "";
                if (File.Exists(edgePath)) targetBrowser = edgePath;
                else if (File.Exists(chromePath)) targetBrowser = chromePath;

                string profileDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "tunemusic", "profile");
                if (!Directory.Exists(profileDir))
                {
                    Directory.CreateDirectory(profileDir);
                }

                if (!string.IsNullOrEmpty(targetBrowser))
                {
                    string browserArgs = string.Format("--app=\"{0}\" --user-data-dir=\"{1}\" --window-size=1440,900 --start-maximized", serverUrl, profileDir);
                    ProcessStartInfo psiApp = new ProcessStartInfo
                    {
                        FileName = targetBrowser,
                        Arguments = browserArgs,
                        UseShellExecute = true
                    };
                    Process.Start(psiApp);
                }
                else
                {
                    // Fallback para navegador padrão do sistema
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = serverUrl,
                        UseShellExecute = true
                    });
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show("Erro ao iniciar tunemusic Pro: " + ex.Message, "tunemusic Pro", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private static bool IsServerOnline(string url)
        {
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                request.Timeout = 800;
                request.Method = "GET";
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    return ((int)response.StatusCode >= 200 && (int)response.StatusCode < 500);
                }
            }
            catch (WebException wex)
            {
                HttpWebResponse resp = wex.Response as HttpWebResponse;
                if (resp != null)
                {
                    return ((int)resp.StatusCode >= 200 && (int)resp.StatusCode < 500);
                }
                return false;
            }
            catch
            {
                return false;
            }
        }
    }
}
