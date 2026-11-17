# Packaging

Two artifacts, two purposes:

| 产物 | 用途 | 怎么来 |
|---|---|---|
| `PDFMend-<ver>-windows-x64.zip` | 主发布：解压双击 `PDFMend.exe`，不需要 Python | `packaging/build.ps1` 或 `release-windows` 工作流 |
| `PDFMend-<ver>-setup-x64.exe` | 可选安装版：装到当前用户，建开始菜单项 | 本文件下面的任一方式 |

## 构建免安装包

```powershell
powershell -File packaging\build.ps1
```

它依次执行：`pip install -e ".[dev,desktop,build]"` → `pytest` → PyInstaller（onedir）→ 打 zip → 打印 SHA256。

产物在 `dist\`：`PDFMend\`（文件夹）、`PDFMend-<ver>-windows-x64.zip`。

## 构建安装版（setup.exe）

`packaging/installer.iss` 是 Inno Setup 6 脚本，输入是 `dist\PDFMend\`。

### 方式 A：本机装了 Inno Setup（Windows）

```powershell
iscc packaging\installer.iss            # 版本号取脚本默认值
iscc /DAppVersion=0.6.0 packaging\installer.iss
```

产物：`dist\PDFMend-0.6.0-setup-x64.exe`。

### 方式 B：没装 Inno Setup，用 Docker + Wine（本仓库验证过）

```powershell
docker run --rm -v "${PWD}:/work" -w /work amake/innosetup:latest `
    /DAppVersion=0.6.0 packaging/installer.iss
```

镜像自带 `iscc`（入口点），不要再写一遍 `iscc`，否则会报
`You may not specify more than one script filename`。

### 方式 C：GitHub Actions

手动触发 `installer` 工作流（`.github/workflows/installer.yml`），
产物在 Actions 的 `PDFMend-installer` artifact 里。

> 注意：`release-windows` 只发 zip，安装版单独产出。原因是构建机若拉不到
> Inno Setup（网络受限），不该把整个 Release 拖红。

## 版本号

`pyproject.toml` 与 `src/pdfmend/__init__.py` 里的版本必须一致；
`installer.iss` 的 `#define AppVersion` 默认值只是兜底，构建时用 `/DAppVersion=` 覆盖即可。
