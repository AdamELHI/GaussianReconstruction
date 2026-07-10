from PySide6.QtCore import QTimer


class PlayController:
    """
    Controleur de lecture des snapshots du SOM.
    """

    def __init__(self, model, view):
        self.model = model
        self.view = view

        self.frames = None
        self.current_index = 0
        self.is_playing = False
        self.loop = False
        self.fps = 20
        self.snapshot_every = 1

        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

    def set_frames(self, frames):
        if frames is None or len(frames) == 0:
            self.frames = None
            self.current_index = 0
            self.is_playing = False
            return

        self.frames = frames
        self.current_index = 0
        self.is_playing = False
        self.show_current_frame()


    def load_frames(self):
        self.view.hide_legend()
        frames = self.model.get_snapshot_neurone()
        if len(frames) == 0:
            raise ValueError("Le mode neurone est disponible seulement en dimension 1, 2 ou 3")
        self.set_frames(frames)


    def play(self):
        if not self.has_frames():
            return

        self.is_playing = True
        self.timer.start(int(1000 / self.fps))

    def pause(self):
        self.is_playing = False

        if self.timer is not None:
            self.timer.stop()

    def stop(self):
        self.is_playing = False
        self.current_index = 0

        if self.timer is not None:
            self.timer.stop()

        if self.has_frames():
            self.show_current_frame()

    def next_frame(self):
        if not self.has_frames():
            return

        if self.current_index < len(self.frames) - 1:
            self.current_index += 1
        else:
            if self.loop:
                self.current_index = 0
            else:
                self.pause()
                return

        self.show_current_frame()

    def previous_frame(self):
        if not self.has_frames():
            return

        if self.current_index > 0:
            self.current_index -= 1

        self.show_current_frame()

    def go_to_frame(self, index):
        if not self.has_frames():
            return

        if index < 0:
            index = 0
        if index >= len(self.frames):
            index = len(self.frames) - 1

        self.current_index = index
        self.show_current_frame()

    def set_fps(self, fps):
        if fps <= 0:
            raise ValueError("fps doit etre strictement positif")

        self.fps = fps

    def show_current_frame(self):
        if not self.has_frames():
            return

        frame = self.frames[self.current_index]
        self.view.display_image(frame)

        iteration = self.current_index * self.snapshot_every
        self.view.update_iteration_label(iteration)
        self.view.update_slider(self.current_index, len(self.frames) - 1)

    def set_loop(self, loop):
        self.loop = bool(loop)

    def has_frames(self):
        return self.frames is not None and len(self.frames) > 0

    def get_current_index(self):
        return self.current_index

    def get_frame_count(self):
        if not self.has_frames():
            return 0
        return len(self.frames)
