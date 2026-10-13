// 글자 색 문법 {빨강|글자}의 이름 -> 색 키. 에디터(라이브 표시·서식 버튼)가 함께 쓴다.
// 실제 색(라이트·다크 두 벌)은 style.css의 --tc-<키> 변수, 클래스는 cm-tc-<키>
export const TEXT_COLORS = { 빨강: "red", 주황: "orange", 노랑: "yellow", 초록: "green", 파랑: "blue", 보라: "purple", 분홍: "pink", 회색: "gray" };
export const COLOR_NAMES = Object.keys(TEXT_COLORS);
const ALT = COLOR_NAMES.join("|");
export const COLOR_OPEN = new RegExp(`\\{(${ALT})\\|`, "g"); // 여는 표시 "{이름|"
export const COLOR_OPEN_END = new RegExp(`\\{(${ALT})\\|$`); // 글 끝의 여는 표시
export const COLOR_WRAPPED = new RegExp(`^\\{(${ALT})\\|([^]*)\\}$`); // 통째로 감싼 글
