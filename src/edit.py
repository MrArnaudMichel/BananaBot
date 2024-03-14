import copy
from datetime import timedelta

import assemblyai as aai
import srt
from moviepy.editor import *
from moviepy.video.tools.subtitles import SubtitlesClip
from termcolor import colored

from scipy.ndimage import gaussian_filter


def blur(image):
    """ Returns a blurred (radius=2 pixels) version of the image """
    return gaussian_filter(image.astype(float), sigma=2)


class Edit:
    """
    Edit class to edit the video.
    """

    def __init__(self, video_name, fileManager, config):
        aai.settings.api_key = config.api_key
        self.config = config
        self.fileManager = fileManager
        self.video_name = video_name
        self.video = VideoFileClip("downloads/" + video_name + ".mp4")
        self.transcript = None

    def transcribe_video(self):
        """
        Transcribes the video using AssemblyAI.
        """
        print(colored("> Transcribing video...", "green"))
        self.transcript = aai.Transcriber().transcribe("downloads/" + self.video_name + ".mp4", config=aai.types.
                                                       TranscriptionConfig(
            auto_highlights=True,
            speaker_labels=True
        ))

    def get_subtitles(self, start_end, index=0):
        """
        Gets the subtitles for a part of the video.
        :param start_end:
        :param index:
        :return:
        """
        start, end = start_end
        subtitles = copy.copy(self.transcript.export_subtitles_srt())

        subs = list(srt.parse(subtitles))

        subs = [sub for sub in subs if start <= sub.start.total_seconds() <= end]

        for i, sub in enumerate(subs):
            sub.start -= timedelta(seconds=start)
            sub.end -= timedelta(seconds=start)

        subtitles = srt.compose(subs)
        return subtitles

    def split_part(self, video_path, start_end, subtitles, i):
        """
        Downloads a part of the video with subtitles and satisfying video.
        :param video_path:
        :param start_end:
        :param subtitles:
        :param i:
        """
        print(colored(f"> Splitting part {i}...", "green"))
        start, end = start_end
        video: VideoFileClip = VideoFileClip(video_path).subclip(start, end)

        video = self.edit_with_options(video, subtitles, i)

        f = open("subtitles.srt", "w")
        f.write(subtitles)
        f.close()
        print(colored("> Adding subtitles...", "green"))
        if self.config.transcribe:
            subtitles_clip = SubtitlesClip("subtitles.srt",
                                           lambda txt: TextClip(txt, font=self.config.font,
                                                                fontsize=self.config.font_size,
                                                                color=self.config.font_color)).set_duration(
                video.duration)
            final = CompositeVideoClip([video, subtitles_clip.set_position(('center', 'center'))],
                                       size=(self.config.width, self.config.height))
        print(colored(f"> Rendering part {i}...", "green"))
        os.makedirs(f"uploads/{self.video_name}", exist_ok=True)
        final.write_videofile(f"uploads/{self.video_name}/part{i}.mp4", threads=self.config.threads, fps=24)

    def split_video(self, seconds: int = 60, from_end: int = 5):
        """
        Splits the video into parts.
        :param seconds:
        :param from_end:
        """
        video_path = "downloads/" + self.video_name + ".mp4"
        start = 0
        end = seconds
        i = 1
        tasks = []
        if self.transcript is None:
            self.transcribe_video()
        while end < self.video.duration:
            print(start, end)
            subtitles = self.get_subtitles((start, end - (i - 1) * from_end), i - 1)
            tasks.append((video_path, (start, end), subtitles, i))
            start = end - from_end
            end += seconds - from_end

            i += 1
        tasks.append((video_path, (start, self.video.duration), subtitles, i))
        for task in tasks:
            self.split_part(*task)
        os.remove("subtitles.srt")
        print(colored("> Done splitting video.", "green"))

    def edit_with_options(self, video, subtitles, i):
        """
        Edits the video with the options from the config file.
        :param video:
        :param subtitles:
        :param i:
        :return:
        """
        original_width = video.w
        original_height = video.h

        if self.config.satisfying == "":
            # Calculating new dimensions for the main video while maintaining aspect ratio
            new_width = self.config.width * 1.5
            ratio = new_width / original_width
            new_height = int(original_height * ratio)
            video = video.resize(width=new_width, height=new_height)
            video = video.set_position(('center', 'center'))
            background = video.fl_image(blur)
            background = background.resize(width=self.config.width, height=self.config.height)
            video = CompositeVideoClip([background, video], size=(self.config.width, self.config.height))
        else:
            satisfying = VideoFileClip(self.config.satisfying)
            if satisfying.duration < 60:
                satisfying = satisfying.subclip(0, satisfying.duration)
            else:
                satisfying = satisfying.subclip(i * 60 - ((i != 1) * 5), i * 60 - ((i != 1) * 5) + 60)
            new_video_width = self.config.width * 2
            ratio = new_video_width / original_width
            new_video_height = int(original_height * ratio)

            new_satisfying_height = self.config.height - new_video_height
            ratio = new_satisfying_height / satisfying.h
            new_satisfying_width = int(satisfying.w * ratio)
            satisfying = satisfying.resize(width=new_satisfying_width, height=new_satisfying_height)
            satisfying = satisfying.volumex(0)
            video.set_position((0, 0))
            video = video.resize(width=new_video_width, height=new_video_height)
            video = CompositeVideoClip(
                [video.set_position(('center', 'top')), satisfying.set_position(('center', 'bottom'))],
                size=(self.config.width, self.config.height))

        if self.config.music != "":
            music = AudioFileClip(self.config.music)
            music.set_duration(video.duration)
            music = music.volumex(self.config.music_volume)
            video = video.set_audio(music)
        return video