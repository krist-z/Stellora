---
name: coding-standards
description: C++ / Qt 项目的编码规范与风格指南。在编写、审阅或重构代码时使用，以确保与项目规范保持一致。
---

# 编码规范

## 通用原则

- **默认使用面向对象范式**：以类和对象为核心组织代码，封装数据与行为，优先使用继承、多态与组合来建模业务逻辑。仅在性能关键路径或明确需要时，才考虑过程式或函数式风格。

## 命名规范

- **变量与函数**：使用小驼峰命名（lower camelCase）。示例：`int maxCount`，`void processData()`。
- **类、结构体、枚举与类型别名**：使用大驼峰命名（upper PascalCase）。示例：`class DataProcessor`，`struct Point2D`。
- **类成员变量**：使用带 `m_` 前缀的小驼峰命名。示例：`int m_maxCount`。
- **全局常量 / 宏**：使用全大写下划线命名（UPPER_SNAKE_CASE）。示例：`const int MAX_BUFFER_SIZE = 1024`。

## 代码格式

- **花括号独占一行**：左花括号与右花括号始终单独占一行。
- **始终使用花括号**：每个 `if`、`else`、`for`、`while` 和 `do` 代码块都必须使用花括号，即使只有一行。

## 代码审查清单

（TODO：添加代码审查清单项）

## 语言特定规则

### C++

- 使用 C++11 至 C++17 标准。除非经明确批准，否则避免使用 C++20 特性。
- 优先使用 `nullptr`，而非 `NULL` 或 `0`。
- 在 `auto` 能提高可读性的地方使用它，但在类型不明显时避免使用。
- 遍历容器时优先使用基于范围的 for 循环。
- 使用智能指针（`std::unique_ptr`、`std::shared_ptr`），避免裸指针的 `new`/`delete`。

### Qt

#### QML 代码格式

- **花括号独占一行**：在 QML 中，左花括号与右花括号始终单独占一行，与 C++ 保持一致。
- **始终使用花括号**：每个 `if`、`else`、`for`、`while` 代码块都必须使用花括号，即使只有一行。禁止写成内联形式 `if (cond) return`。

**正确：**
```qml
if (currentForm === form)
{
    return;
}
```

**错误：**
```qml
if (currentForm === form) return
```

#### QML Id 前缀规则

每个带有 `id` 的 QML 元素必须使用表明其组件类型的**小驼峰命名（lower camelCase）**前缀。每个 QML 文件的根元素必须使用 `id: root`。

**标准前缀：**

| 组件 | 前缀 | 示例 |
|-----------|--------|---------|
| 根元素 | `root` | `id: root` |
| Rectangle | `rect` | `id: rectBackground` |
| Button | `btn` | `id: btnConfirm` |
| CheckBox | `chk` | `id: chkAutoFilter` |
| ComboBox | `cbx` | `id: cbxLanguage` |
| RadioButton | `rdo` | `id: rdoUsb1` |
| Switch | `swt` | `id: swtDisplay` |
| Slider | `sld` | `id: sldVolume` |
| ProgressBar | `pgb` | `id: pgbStartup` |
| SpinBox | `spb` | `id: spbIntensity` |
| Text | `txt` | `id: txtTitle` |
| Label | `lbl` | `id: lblVersion` |
| TextField | `tf` | `id: tfInputId` |
| TextEdit | `te` | `id: teComment` |
| TextInput | `ti` | `id: tiSearch` |
| Image | `img` | `id: imgLogo` |
| MouseArea | `ma` | `id: maClick` |
| ListView | `lsv` | `id: lsvFileList` |
| Repeater | `rpt` | `id: rptItems` |
| Row / RowLayout | `row` | `id: rowButtons` |
| Column / ColumnLayout | `col` | `id: colSettings` |
| Grid / GridLayout | `grid` | `id: gridKeys` |
| StackView | `stk` | `id: stkMain` |
| TabBar | `tb` | `id: tbMain` |
| GroupBox | `grp` | `id: grpDetails` |
| Dialog / Popup | `dlg` / `popup` | `id: dlgConfirm` |
| FileDialog | `fd` | `id: fdOpen` |
| Timer | `timer` | `id: timerUpdate` |
| Animation | `anim` | `id: animFade` |
| Canvas | `canvas` | `id: canvasDraw` |
| Shape | `shape` | `id: shapeLine` |
| Path | `path` | `id: pathCurve` |
| ChartView | `cv` | `id: cvTrend` |
| Item（通用容器） | `item` | `id: itemWrapper` |
| 自定义组件 | lower camelCase | `id: customChart`，`id: statusBar` |

**注意事项：**
- 前缀是强制的；后缀应使用小驼峰命名描述元素的用途。
- 禁止**直接使用裸 `id`**，如 `id: checkBox` 或 `id: button`。必须始终包含前缀。
- 禁止**使用完整组件名作为前缀**（例如避免 `id: mouseArea`、`id: chartView`、`id: progressBar`）。应使用上表中的缩写前缀。
- `chk`（CheckBox）与 `cbx`（ComboBox）故意设计为不同，以避免混淆。
- Image 元素优先使用 `img` 而非 `image`。
- 对于自定义项目组件，遵循该组件自身的小驼峰命名规范（例如 `customChart`、`statusBar`）。

## 反面模式

- 禁止**在源文件（`.cpp`）中使用匿名命名空间**。应使用具名命名空间或文件作用域的 `static`。
